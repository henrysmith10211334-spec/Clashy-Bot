# YouTube → Discord Announcer Bot

Posts a message in a Discord channel when a new video/Short is uploaded,
and a separate "LIVE NOW" message when the channel starts streaming.

# Clashy's Bot — YouTube Announcer + Leveling + Invite Tracker

Three features in one bot:
1. **YouTube announcer** — posts when a new video/Short is uploaded or a
   livestream starts
2. **Leveling system** — members earn XP from chatting, level up, `/rank`
   and `/leaderboard`
3. **Invite tracker** — logs who invited each new member, `/invites` and
   `/invite-leaderboard`

## How YouTube detection works

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
3. Under **Privileged Gateway Intents**, turn **ON**: **"Server Members
   Intent"** — required for the invite tracker to detect when someone joins
4. Click "Reset Token" / "Copy" to get your **bot token** — keep this secret
5. Go to "OAuth2" → "URL Generator":
   - Scopes: `bot`
   - Bot Permissions: `Send Messages`, `Embed Links`, **`Manage Server`**
     (needed to read invite use-counts), `Manage Roles` (only if you plan
     to add level-up role rewards later)
   - Open the generated URL and add the bot to your server

   If the bot is already in your server from before, you'll need to
   re-invite it with this updated permission set (or grant "Manage Server"
   directly via Server Settings → Roles → the bot's role).

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
   - `DISCORD_CHANNEL_ID` = the Discord channel ID (for YouTube announcements)
   - `YOUTUBE_CHANNEL_ID` = the `UC...` YouTube channel ID
   - `PUBLIC_URL` = the domain from step 3, e.g.
     `https://yourapp-production.up.railway.app` (no trailing slash)
   - `LOG_CHANNEL_ID` = the channel ID where invite-join logs should post
   - `CHECK_INTERVAL_MINUTES` = `15` (optional — backup poll only)
   - `LIVE_CHECK_INTERVAL_MINUTES` = `2` (optional)
   - `LEVEL_UP_CHANNEL_ID` = optional — if unset, level-up messages post in
     whatever channel the member was chatting in
   - `GUILD_ID` = optional — your Discord server's ID. If set, slash
     commands (`/rank`, `/invites`, etc.) show up **instantly**. If unset,
     they still work, but can take up to an hour to propagate globally.
   - `DB_PATH` = see the **Persistent storage** section below — important!
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

## Leveling system

- Members earn 15–25 random XP per message, with a 60-second cooldown per
  person (so spamming doesn't farm levels)
- Level-up posts: "🎉 [user] just reached Level N!" in the channel they
  were chatting in (or `LEVEL_UP_CHANNEL_ID` if you set one)
- `/rank [member]` — check your level/XP, or someone else's
- `/leaderboard` — top 10 by XP

To change the XP curve or amount, edit `XP_MIN`, `XP_MAX`, and
`xp_for_level()` in `leveling.py`.

## Invite tracker

- When someone joins, the bot compares invite use-counts to figure out
  which invite link was used, then posts to `LOG_CHANNEL_ID`:
  `📥 [user] joined — invited by [inviter] (now N invites)`
- If it can't determine the inviter (vanity URL, expired invite), it logs
  that instead, with no count change
- `/invites [member]` — check someone's total invite count
- `/invite-leaderboard` — top 10 inviters

This requires the bot to have the **Manage Server** permission (see step 1)
and **Server Members Intent** enabled in the Developer Portal — without
both, invite tracking silently won't work (check the logs for a permission
warning).

## ⚠️ Persistent storage (important!)

Leveling and invite data live in a SQLite file (`bot_data.db` by default).
**On Railway, a redeploy wipes the container's disk** — meaning everyone's
levels and invite counts would reset to zero every time you push an update.
That's fine for the YouTube cache (it just re-caches quietly) but NOT fine
for XP/invites people have earned over time.

**Fix: attach a Railway Volume.**
1. In your Railway service → **Settings → Volumes** → "Add Volume"
2. Mount it at `/data`
3. Set the env var `DB_PATH` = `/data/bot_data.db`
4. Redeploy

Now the database survives redeploys, restarts, and crashes. Do this before
the bot goes live for real — once people start earning levels, you don't
want to wipe their progress.

## Slash commands summary

| Command | Description |
|---|---|
| `/rank [member]` | Check level + XP |
| `/leaderboard` | Top 10 XP |
| `/invites [member]` | Check invite count |
| `/invite-leaderboard` | Top 10 inviters |
| `/invites-add member amount` | **[Admin]** Add/subtract invites (negative `amount` to subtract) |
| `/invites-reset member` | **[Admin]** Reset one member's invites to 0 |
| `/invites-reset-all confirm` | **[Admin]** Reset everyone's invites — requires `confirm: True` |

The admin commands require the **Manage Server** permission. They're
hidden from regular members by default (Discord enforces this), but a
server owner could change that visibility in Server Settings → Integrations
if they ever wanted to.

If commands don't show up in Discord, double check `GUILD_ID` is set (for
instant sync) or wait up to an hour for global sync, and make sure you've
redeployed since adding these commands.
