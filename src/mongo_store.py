"""MongoDB persistence with DATA LOSS PREVENTION.
CRITICAL: Never overwrites with fewer users. Recovers from backups.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from config import MONGO_DB, MONGO_URI
from db import db

PERSISTED_TABLES = (
    "users", "history", "plans", "coupons", "coupon_uses", "admins",
    "settings", "stats", "payments", "audit_logs", "follows",
)
NON_MOVIE_TABLES = PERSISTED_TABLES
# Movie catalog is also persisted so the bot survives restarts without a full rescan.
MOVIE_TABLES = ("movies",)

_client = None
_collection = None
_save_lock = asyncio.Lock()
MOVIE_CHUNK_SIZE = 5000
# Atlas free tier = 512 MB. Big log tables are capped before saving and movie
# chunks are zlib-compressed (~6-10x smaller), so the quota never fills again.
STATE_TABLE_CAPS = {"audit_logs": 3000, "history": 8000, "stats": 5000}


def _pack_rows(rows: list) -> bytes:
    import json, zlib
    return zlib.compress(json.dumps(rows, default=str, separators=(",", ":")).encode(), 6)


def _unpack_chunk(chunk: dict) -> list:
    if chunk.get("z") is not None:
        import json, zlib
        return json.loads(zlib.decompress(bytes(chunk["z"])).decode())
    return chunk.get("rows", [])


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "space quota" in text or "over your space" in text or getattr(exc, "code", None) == 8000


async def free_space(collection=None) -> None:
    """Emergency cleanup when Atlas blocks writes: deletes are still allowed."""
    try:
        if collection is None:
            collection = await _collection_or_none()
        if collection is None:
            return
        await purge_orphan_chunks(collection)
        # Legacy/backup docs from older versions.
        res = await collection.delete_many({"_id": {"$regex": "^(backup|state_backup|snapshot)"}})
        if res.deleted_count:
            logging.info("Mongo freed %d legacy backup docs", res.deleted_count)
        try:
            await collection.database.command({"compact": collection.name})
        except Exception:
            pass
    except Exception as exc:
        logging.warning("Mongo free_space failed: %s", exc)


async def _collection_or_none():
    global _client, _collection
    if not MONGO_URI:
        return None
    if _collection is None:
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
            _client = AsyncIOMotorClient(
                MONGO_URI,
                serverSelectionTimeoutMS=10000,
                connectTimeoutMS=10000,
                socketTimeoutMS=30000,
                maxPoolSize=20,
                minPoolSize=2
            )
            _collection = _client[MONGO_DB]["bot_state"]
            try:
                await asyncio.wait_for(_client.admin.command("ping"), timeout=12.0)
                logging.info("MongoDB connected")
            except asyncio.TimeoutError:
                logging.warning("MongoDB timeout")
                _client.close()
                _client = None
                _collection = None
                return None
            except Exception as e:
                logging.warning(f"MongoDB ping failed: {e}")
                _client.close()
                _client = None
                _collection = None
                return None
        except Exception as e:
            logging.warning(f"MongoDB connection failed: {e}")
            _client = None
            _collection = None
            return None
    return _collection


async def restore_non_movie_state():
    """Restore from MongoDB."""
    try:
        collection = await _collection_or_none()
        if collection is None:
            return False
        document = await collection.find_one({"_id": "state"})
        if not document:
            return False
        tables = {name: document.get("tables", {}).get(name, []) for name in NON_MOVIE_TABLES}
        await db.import_state({"version": 2, "tables": tables})
        user_count = await db.user_count()
        logging.info(f"Mongo restored: users={user_count}")
        return True
    except Exception:
        logging.exception("Mongo restore failed")
        return False


async def restore_movie_catalog():
    """Restore movie catalog from MongoDB so stats survive restarts."""
    try:
        collection = await _collection_or_none()
        if collection is None:
            return False
        document = await collection.find_one({"_id": "movies"})
        if not document:
            return False
        if document.get("chunked"):
            chunk_count = max(0, int(document.get("chunk_count", 0)))
            generation = str(document.get("generation", ""))
            restored_any = False
            for offset in range(0, chunk_count, 20):
                ids = [
                    f"movies:{generation}:{index}" if generation else f"movies:{index}"
                    for index in range(offset, min(offset + 20, chunk_count))
                ]
                chunks = await collection.find({"_id": {"$in": ids}}).to_list(length=len(ids))
                by_id = {chunk["_id"]: chunk for chunk in chunks}
                for chunk_id in ids:
                    rows = _unpack_chunk(by_id.get(chunk_id, {}))
                    if rows:
                        await db.import_state({"version": 3, "tables": {"movies": rows}})
                        restored_any = True
            if not restored_any and int(document.get("count", 0)):
                logging.warning("Mongo movie manifest exists but its chunks are missing")
                return False
        else:
            # Backward compatibility with the old single-document layout.
            rows = document.get("rows", [])
            if not rows:
                return False
            for offset in range(0, len(rows), 2000):
                await db.import_state({"version": 2, "tables": {"movies": rows[offset:offset + 2000]}})
        movie_count = await db.movie_count()
        logging.info(f"Mongo restored movie catalog: {movie_count} movies")
        return True
    except Exception:
        logging.exception("Mongo movie catalog restore failed")
        return False


async def save_movie_catalog(_retry: bool = True):
    """Save movie catalog to MongoDB in compressed batches (low RAM, low disk)."""
    collection = None
    generation = None
    try:
        collection = await _collection_or_none()
        if collection is None:
            return False
        now = datetime.now(timezone.utc)
        generation = now.strftime("%Y%m%dT%H%M%S%f")
        previous = await collection.find_one({"_id": "movies"}, {"generation": 1, "chunk_count": 1})
        await purge_orphan_chunks(collection, previous)
        chunk_count = 0
        row_count = 0
        after_msg_id = 0
        while True:
            chunk = await db.export_movie_catalog_batch(after_msg_id, MOVIE_CHUNK_SIZE)
            if not chunk:
                break
            await asyncio.wait_for(
                collection.replace_one(
                    {"_id": f"movies:{generation}:{chunk_count}"},
                    {"_id": f"movies:{generation}:{chunk_count}", "version": 4,
                     "generation": generation, "updated_at": now, "z": _pack_rows(chunk), "n": len(chunk)},
                    upsert=True,
                ),
                timeout=30.0,
            )
            chunk_count += 1
            row_count += len(chunk)
            after_msg_id = int(chunk[-1]["msg_id"])
        await collection.replace_one(
            {"_id": "movies"},
            {"_id": "movies", "version": 4, "updated_at": now, "count": row_count,
             "chunked": True, "generation": generation, "chunk_count": chunk_count},
            upsert=True,
        )
        old_generation = str((previous or {}).get("generation", ""))
        old_chunk_count = int((previous or {}).get("chunk_count", 0))
        if old_chunk_count:
            old_ids = [
                f"movies:{old_generation}:{i}" if old_generation else f"movies:{i}"
                for i in range(old_chunk_count)
            ]
            await collection.delete_many({"_id": {"$in": old_ids}})
        logging.info(f"Mongo saved movie catalog: {row_count} movies in {chunk_count} compressed chunks")
        return True
    except asyncio.TimeoutError:
        logging.warning("Mongo movie catalog save timeout")
        await _drop_generation_safe(collection, generation)
        return False
    except Exception as e:
        await _drop_generation_safe(collection, generation)
        if _retry and _is_quota_error(e) and collection is not None:
            # Quota full: the old (uncompressed) generation is what fills the disk.
            # The catalog is still safe in local SQLite and in MAIN_DATA itself, so
            # drop the old generation and write the compressed one in its place.
            logging.warning("Mongo quota full — dropping old catalog and rewriting compressed")
            try:
                await collection.delete_many({"_id": {"$regex": "^movies"}})
                await free_space(collection)
            except Exception as exc:
                logging.warning("Mongo quota recovery failed: %s", exc)
            return await save_movie_catalog(_retry=False)
        logging.warning(f"Mongo movie catalog save error: {type(e).__name__}: {str(e)[:200]}")
        return False


async def _drop_generation_safe(collection, generation) -> None:
    """Remove a partially written generation so failed saves never leak space."""
    if collection is None or not generation:
        return
    try:
        manifest = await collection.find_one({"_id": "movies"}, {"generation": 1})
        if (manifest or {}).get("generation") == generation:
            return  # it was published; keep it
        await collection.delete_many({"_id": {"$regex": f"^movies:{generation}:"}})
    except Exception as exc:
        logging.warning("Mongo partial-generation cleanup failed: %s", exc)


async def purge_orphan_chunks(collection=None, manifest=None) -> int:
    """Delete every movies:* chunk not referenced by the live manifest. Deletes are
    allowed even when Atlas blocks writes for quota, so this recovers the cluster."""
    try:
        if collection is None:
            collection = await _collection_or_none()
        if collection is None:
            return 0
        if manifest is None:
            manifest = await collection.find_one({"_id": "movies"}, {"generation": 1, "chunk_count": 1})
        gen = str((manifest or {}).get("generation", ""))
        keep = {f"movies:{gen}:{i}" if gen else f"movies:{i}"
                for i in range(int((manifest or {}).get("chunk_count", 0)))}
        query = {"_id": {"$regex": "^movies:", "$nin": list(keep)}}
        result = await collection.delete_many(query)
        if result.deleted_count:
            logging.info("Mongo purged %d orphan movie chunks", result.deleted_count)
        return int(result.deleted_count)
    except Exception as exc:
        logging.warning("Mongo orphan purge failed: %s", exc)
        return 0


async def save_non_movie_state():
    """Save with DATA LOSS PREVENTION - never reduces user count."""
    try:
        async with _save_lock:
            collection = await _collection_or_none()
            if collection is None:
                return False
            
            current_users = await db.user_count(include_banned=True)
            
            # CRITICAL SAFETY CHECK: Fetch existing data
            existing_doc = None
            try:
                existing_doc = await asyncio.wait_for(
                    collection.find_one({"_id": "state"}),
                    timeout=10.0
                )
            except Exception:
                pass
            
            if existing_doc:
                old_tables = existing_doc.get("tables", {})
                stored_users = len(old_tables.get("users", []))
                
                # DATA LOSS PREVENTION: Never save if we have FEWER users
                if current_users < stored_users:
                    logging.warning(
                        f"DATA PROTECTION: Not saving! "
                        f"Current users ({current_users}) < Stored users ({stored_users}). "
                        f"Preventing data loss!"
                    )
                    return False
                
                # Merge users (keep all)
                state = await db.export_tables(NON_MOVIE_TABLES)
                new_tables = {name: state["tables"].get(name, []) for name in NON_MOVIE_TABLES}
                
                # Merge user lists
                old_user_list = old_tables.get("users", [])
                new_user_list = new_tables.get("users", [])
                
                user_dict = {}
                for u in old_user_list:
                    uid = u.get("user_id")
                    if uid:
                        user_dict[uid] = u
                for u in new_user_list:
                    uid = u.get("user_id")
                    if uid:
                        user_dict[uid] = u
                
                final_tables = dict(new_tables)
                final_tables["users"] = list(user_dict.values())

                logging.info(f"Mongo save: users merged {stored_users}+{current_users}->{len(final_tables['users'])}")
            else:
                state = await db.export_tables(NON_MOVIE_TABLES)
                final_tables = {name: state["tables"].get(name, []) for name in NON_MOVIE_TABLES}
            
            for table, cap in STATE_TABLE_CAPS.items():
                rows = final_tables.get(table) or []
                if len(rows) > cap:
                    final_tables[table] = rows[-cap:]
            doc = {"_id": "state", "version": 2, "updated_at": datetime.now(timezone.utc), "tables": final_tables}
            try:
                await asyncio.wait_for(collection.replace_one({"_id": "state"}, doc, upsert=True), timeout=30.0)
                return True
            except Exception as exc:
                if not _is_quota_error(exc):
                    raise
                logging.warning("Mongo quota full on state save — freeing space and retrying")
                await free_space(collection)
                await collection.delete_many({"_id": {"$regex": "^movies"}})  # catalog re-saves compressed
                await asyncio.wait_for(collection.replace_one({"_id": "state"}, doc, upsert=True), timeout=30.0)
                try:
                    from snapshot import request_catalog_save
                    await request_catalog_save(delay=5)
                except Exception:
                    pass
                return True
    except asyncio.TimeoutError:
        logging.warning("Mongo save timeout")
        return False
    except Exception as e:
        logging.warning(f"Mongo save error: {type(e).__name__}: {str(e)[:200]}")
        return False


async def close_mongo():
    global _client, _collection
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
    _client = None
    _collection = None


__all__ = ["free_space", "purge_orphan_chunks", "PERSISTED_TABLES", "NON_MOVIE_TABLES", "MOVIE_TABLES", "restore_non_movie_state", "save_non_movie_state", "restore_movie_catalog", "save_movie_catalog", "close_mongo"]
