# 📺 TV Show Bot

[![Deploy on Heroku](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/oyevipthoma88/Tv-show-bot)

Telegram TV show bot — non-admin channel se **live mirror**, har naya episode turant MAIN_DATA me, users ko **sabse naya episode sabse upar 📅 date ke saath**, show follow karke **new-episode alert**, force-join verify, free/premium limits, UPI payments aur full owner panel.

## 📺 TV Features (new)

- **Season / Episode detection** — `Anupamaa 28th October 2026 Episode 1234`, `Mirzapur S03E05`, `Taarak Mehta 4570 28.10.2026` sab samajh aata hai; show name clean rehta hai
- **Specific episode search** — `Anupamaa episode 1234` / `Mirzapur S2E3` bhejo, sirf wahi episode
- **Results** — `📅 29 Oct • Anupamaa • E1234 • 720p • 350MB`, sabse naya upar + **📂 Saare Episodes** + **🔔 Follow**
- **🆕 Latest Uploads** — aaj kitne naye episodes + saare uploads newest-first (pages)
- **🔔 My Shows / New Episode Alert** — follow kiye show ka naya episode aate hi ek message (burst me bhi ek hi message per show)
- **Owner Panel dashboard** — users, episodes, last-24h uploads, login status, live mirror status ek nazar me

## Features

**Users**
- Start → maximum **5 must-join channels/URLs** + **Verify** button (verify hone par hi panel milega)
- 📺 **Search TV Show** — naam type karo (galat spelling chalega) ya 🎤 voice note bhejo; DM aur group dono me plain movie name se direct search hoti hai
- Saare matching results quality/size ke saath buttons me; tap karte hi file channel se aa jati hai
- 📘 Tutorial, 🕘 Last History, 🎥 Watch Online, 💎 Premium, 🎟 Redeem Coupon, 🎁 Refer & Earn
- Free plan: pehle din **3 search**, uske baad **roz 1**
- Movie na mile to owner request log hoti hai aur catalog me available movies ki suggestions milti hain; users ko sirf MAIN_DATA me indexed content deliver hota hai

**Premium**
- Plans: 1 Day ₹25 · 7 Days ₹149 · 1 Month ₹449 · 1 Year ₹2999 · Lifetime ₹4999 (owner panel se editable)
- Plan select → QR/UPI → screenshot → owner + log channel me details → **Approve/Reject** button
- Coupon codes bhi support hain

**Referral**
- `https://t.me/<bot>?start=ref_<userid>`
- 3 referral → 1 hour · 5 → 5 hours · 10 → 1 day premium

**Owner Panel** (`/ownerpanel` ya Start ka button; sirf owner ko)
- 🖼 Start pic set (GitHub raw link ya photo)
- 💳 QR set + UPI id
- 💰 Plan price edit · 🎁 Gift premium (userid + days)
- 🎟 Coupon code banao · 💎 Premium users list
- 📡 Comma-separated 100+ source movie channels configure karke `/scanall` ya custom range se MAIN_DATA me newest-to-oldest scan; new source upload par owner DMs aur LOG_CHANNEL me **Add to MAIN_DATA / Decline** approval request aati hai
- 🗑 Owner Panel → **Auto Delete** se delivered user messages ko 1 minute–24 hours me automatically delete kar sakte ho; fresh installs aur legacy `0` default installs me default **7 minutes** hai, aur `0` owner manually set karke disable kar sakta hai. Delivery warning aur deletion ke baad available movie suggestions bhi bheji jaati hain
- 📢 Broadcast · 👮 Manage admin · 🔗 Verify URLs add/remove (maximum 5) · 📘 Tutorial set · 🎥 Watch Online bot set · 📊 Stats
- Admin users ko owner panel nahi milta; unka sole action `/addvideo` ya **Add Video** button se forwarded video catalog me add karna hai

## 🆕 Live Mirror (non-admin channels)

- **Multiple joiner accounts**: Owner Panel → 🔐 Login Account → **➕ Add Joiner Account**. Saare accounts parallel me sources watch karte hain; jo pehle naya upload dekhe wahi MAIN_DATA me bhejta hai (duplicate kabhi nahi). Joiner account ko MAIN_DATA admin hone ki zarurat nahi — main account upload kar deta hai
- Search me kuch na mile to **har logged-in account ke joined channels** me ek saath global search hoti hai, aur file seedha user ko milti hai (link nahi)
- Start pic MAIN_DATA me `#START_PIC` ke saath pin hoti hai — reboot ke baad bhi wapas aa jati hai
- MongoDB catalog ab compressed save hota hai; 512 MB quota full hone par bot khud jagah khali karke dobara save karta hai

- Owner Panel → **🔐 Login Account** → API ID/HASH (my.telegram.org) → phone → OTP (spaces ke saath, jaise `1 2 3 4 5`) → 2FA password (agar hai)
- Session MongoDB me save hota hai, restart par auto-login
- Login wala account source channel ka member ho aur **MAIN_DATA me admin** (post permission)
- Owner Panel → **🎞 Source Channels** me non-admin channel ID/@username set karo (user account se resolve hota hai)
- Source me naya upload aate hi turant MAIN_DATA me share + index; bot offline tha to restart par missed uploads (max 200/source) catch-up hote hain
- Protected (forward-restricted) channels: download + re-upload fallback
- **📡 Live Mirror** button se ON/OFF; search results me latest upload sabse upar `📅 date` ke saath

## Setup

1. `pip install -r requirements.txt`
2. `cp .env.example .env` aur values bharo (`BOT_TOKEN`, `OWNER_IDS`, `MAIN_DATA`, `MOVIE_CHANNELS`, `MONGO_URI`); optional `LOG_CHANNEL` set karo
3. Bot ko **MAIN_DATA channel**, **log channel** aur **verify channels** me required permissions do; source chat IDs owner panel se configure honge
4. `python src/main.py`
5. Owner Panel → **Source Channels** me source chat ID(s) comma-separated set karo. New video upload hone par owner DM aur `LOG_CHANNEL` me approval request aayegi. **Add to MAIN_DATA** dabane par source post canonical `MAIN_DATA` me copy/index hogi; **Decline** se skip hogi. Historical content ke liye `/scanall` ya `/scan start_id end_id` chalao. Owner Panel → **Watch Online Bot** se player username set karo; `ONLINE_PLAYER_BOT` fallback ke roop me supported hai. Owner Panel → **Verify URLs** me `add @channel`, `del @channel`, ya `set @one,@two` use karke maximum 5 public channels manage karo. Owner Panel → **Set Tutorial** se clean Hinglish tutorial edit karo.

## Notes
- Telegram flood limits ko respect karte hue scan me bounded parallelism, retry/backoff, aur per-batch durable database commits use hote hain; literally unlimited speed/range Telegram API allow nahi karta.
- `MAIN_DATA` ek canonical storage/catalog channel hai. Bot ko wahan post, copy, pin aur delete permission do. Movie index ab MongoDB me persist hota hai, isliye restart par existing catalog restore hota hai aur historical scan nahi hota. `LOG_CHANNEL` configured ho to latest state snapshot mirror hokar pin hota hai; har movie ki duplicate log copy nahi banti.
- Voice search ke liye `OPENAI_API_KEY` (whisper) set karo; na ho to bot text maangega.
- **Watch Online** button sirf configured player bot ka usage flow dikhata hai: player bot ko group me admin do, voice chat start karo, movie forward/tag karke `vplay` likho. Actual VC playback player bot ki apni implementation par depend karta hai.
- User delivery caption strict compact format me hoti hai: Movie, Quality, Duration, Join, Visit, aur Enjoy lines only. Video/audio metadata se duration detect hoti hai; unknown hone par `Unknown` dikhaya jata hai.
- Files hamesha `copy_message` se bhejti hain, isliye Telegram ki full speed milti hai (koi re-upload nahi). Missing movies ke liye koi external movie-download fallback nahi hai; bot sirf MAIN_DATA catalog se delivery karta hai.

## Deploy
Koi bhi VPS / Railway / Render worker:
```
python src/main.py
```

## Heroku Deploy

1. Upar wale **Deploy on Heroku** button pe click karo
2. App name do, phir `BOT_TOKEN`, `OWNER_IDS`, `MAIN_DATA`, `MOVIE_CHANNELS`, `MONGO_URI` bharo; optional `LOG_CHANNEL` set karo (baki optional)
3. Deploy hone ke baad **Resources** tab me jaake `worker` dyno ON karo; MAIN_DATA aur LOG_CHANNEL dono me bot ko post/copy/pin/delete permissions do
4. Note: Heroku ka filesystem temporary hai — dyno restart par local `bot.db` reset ho sakta hai. Bot MAIN_DATA me compressed pinned state snapshot rakhta hai; isliye MAIN_DATA permissions aur pinned snapshot ko delete na karna zaroori hai.
