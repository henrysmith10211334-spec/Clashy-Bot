# YouTube → Discord Announcer Bot

Posts a message in a Discord channel whenever a new video is uploaded to a
YouTube channel. Checks YouTube's free RSS feed every few minutes — no
YouTube API key needed.

## 1. Create the Discord bot

1. Go to https://discord.com/developers/applications → "New Application"
2. Go to the "Bot" tab → "Add Bot"
3. Under "Privileged Gateway Intents" you don't need to enable anything extra
   (this bot only sends messages, doesn't read them)
4. Click "Reset Token" / "Copy" to get your **bot token** — keep this secret
5. Go to "OAuth2" → "URL Generator":
   - Scopes: `bot`
   - Bot Permissions: `Send Messages`, `Embed Links`
   - Copy the generated URL, open it in your browser, and add the bot to
     your server

## 2. Get your Discord channel ID

In Discord: User Settings → Advanced → enable "Developer Mode".
Then right-click your "videos" channel → "Copy Channel ID".

## 3. Get the YouTube channel ID

This must be the `UC...` ID, not the @handle. Easiest way:
1. Go to the channel's YouTube page
2. View page source (Ctrl+U) and search for `"channelId"`, OR
3. Use a site like https://commentpicker.com/youtube-channel-id.php

## 4. Deploy on Railway

1. Go to https://railway.app and sign in (GitHub login is easiest)
2. Create a new project → "Deploy from GitHub repo" (push this folder to a
   new GitHub repo first), or use "Empty Project" and drag/upload these files
3. In the project's "Variables" tab, add:
   - `DISCORD_TOKEN` = your bot token from step 1
   - `DISCORD_CHANNEL_ID` = the channel ID from step 2
   - `YOUTUBE_CHANNEL_ID` = the UC... ID from step 3
   - `CHECK_INTERVAL_MINUTES` = `5` (optional, defaults to 5)
4. Railway will detect the `Procfile` and run it as a worker automatically
5. Check the "Deployments" → "Logs" tab — you should see `Logged in as
   YourBotName#1234`

That's it. The first time it runs, it just remembers what videos already
exist (no announcement spam for your back-catalog). Every video after that
gets posted automatically.

## Notes

- `seen_videos.json` is created automatically to track which videos have
  already been announced. On Railway's free tier this resets on redeploy —
  that's fine, it'll just re-cache and skip posting old videos again on the
  first check after redeploy.
- If you ever want to test it without waiting, you can temporarily lower
  `CHECK_INTERVAL_MINUTES`, but don't go below 1 — YouTube may rate-limit
  excessive RSS requests.
