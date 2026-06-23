# YouTube → Discord Announcer Bot

Posts a message in a Discord channel when a new video/Short is uploaded,
and a separate "LIVE NOW" message when the channel starts streaming.

## How detection works

- **New videos/Shorts** → near-instant, via YouTube's **WebSub (PubSubHubbub)**
  push notifications. YouTube pings the bot directly the moment something
  publishes, instead of the bot having to repeatedly ask.
- **A slow backup poll** (every 15 min by default) double-checks in case a
  push notification is ever missed — it costs nothing and adds safety.
- **Going live** → still polling-based (checked every 2 min by default),
  since WebSub doesn't reliably signal "stream just started."

⚠️ **Important:** WebSub requires a **public URL that YouTube can reach**.
This means the bot must run somewhere with a real public address (like
Railway) — it can no longer be tested by just running it on your own PC
with nothing else, since YouTube's servers need to be able to call it back.

## 1. Create the Discord bot

1. Go to https://discord.com/developers/applications → "New Application"
2. Go to the "Bot" tab → "Add Bot"
3. No extra Privileged Gateway Intents needed (bot only sends messages)
4. Click "Reset Token" / "Copy" to get your **bot token** — keep this secret
5. Go to "OAuth2" → "URL Generator":
   - Scopes: `bot`
   - Bot Permissions: `Send Messages`, `Embed Links`
   - Open the generated URL and add the bot to your server

## 2. Get your Discord channel ID

In Discord: User Settings → Advanced → enable "Developer Mode".
Right-click your videos channel → "Copy Channel ID".

## 3. Get the YouTube channel ID

Must be the `UC...` ID, not the @handle. If you're on a channel page, click
into a video, click the channel name, and check the URL — if it shows
`youtube.com/channel/UC...`, that's it. Otherwise view page source and
search for `channelId`.

## 4. Deploy on Railway

1. Go to https://railway.app and create a project (upload these files, or
   connect a GitHub repo containing them)
2. Railway will detect the `Procfile` (`web: python bot.py`) and treat this
   as a web service
3. Go to the service's **Settings → Networking** tab → click **"Generate
   Domain"**. Copy the URL it gives you (something like
   `https://yourapp-production.up.railway.app`)
4. Go to the **Variables** tab and add:
   - `DISCORD_TOKEN` = your bot token
   - `DISCORD_CHANNEL_ID` = the Discord channel ID
   - `YOUTUBE_CHANNEL_ID` = the `UC...` YouTube channel ID
   - `PUBLIC_URL` = the domain from step 3, e.g.
     `https://yourapp-production.up.railway.app` (no trailing slash)
   - `CHECK_INTERVAL_MINUTES` = `15` (optional — backup poll only)
   - `LIVE_CHECK_INTERVAL_MINUTES` = `2` (optional)
5. Redeploy. Check the logs — you should see:
   ```
   Logged in as YourBot#1234
   Webhook server listening on port XXXX (path /webhook)
   WebSub: subscription request accepted (callback: https://.../webhook)
   ```
6. Shortly after, YouTube's hub will hit your `/webhook` URL with a
   verification request. You should see in the logs:
   ```
   WebSub: verification GET received (mode=subscribe)
   ```
   If you see that, the push subscription is fully active.

That's it. The first backup-poll cycle just caches existing videos quietly
(no spam of your back-catalog). Every video after that — and any
livestream — gets announced automatically, usually within seconds for new
uploads thanks to WebSub.

## Notes

- The subscription to YouTube's hub auto-renews every ~4 days in the
  background (`resubscribe_loop`) — you don't need to do anything.
- `seen_videos.json` / `live_state.json` are created automatically to avoid
  duplicate posts. On Railway's free/trial tier these reset on redeploy —
  harmless, it just re-caches on the next backup poll.
- If `PUBLIC_URL` is ever wrong or the service redeploys with a new domain,
  just update the `PUBLIC_URL` variable — the next `resubscribe_loop` tick
  (or a manual redeploy) will pick it up and re-subscribe automatically.
- To test detection speed without a real upload, use `reset_seen.py` (forces
  the *backup poll* to re-announce an existing video) — note this only
  tests the polling path, not the WebSub push path, since WebSub only fires
  on real YouTube publish events.
