DTEK Discord bot — updated package

Files:
- bot.py: updated bot source
- requirements.txt: unchanged dependencies from the supplied project
- render.yaml: unchanged Render configuration
- Dockerfile: unchanged container configuration

Deployment:
1. Replace the project's bot.py with this version.
2. Keep the other three files in the project root under exactly the filenames above.
3. Keep the existing Render environment variables: DISCORD_TOKEN, DISCORD_CHANNEL_ID, DATABASE_URL.
4. Deploy/redeploy on Render.

The DTEK page workflow was intentionally left unchanged: URL, selectors, city/street/house values,
click sequence, pop-up handling, CAPTCHA flow, schedule parsing, and screenshot crops were not edited.

Important: the existing web dashboard/API still has no authentication. It was not changed in this update.
