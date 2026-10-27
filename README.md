# The R.A.T.S. Report

A weekly sports publication for the R.A.T.S. fantasy football league on Sleeper, written by a
newsroom of fictional beat reporters. One reporter covers each team.

- `pipeline/fetch.py`: downloads the league (all seasons) from Sleeper, plus NFL play-by-play
- `pipeline/facts.py`: turns that into one `facts.json` per week: scores, lineups, how every
  lead moved through the weekend, transactions with timestamps, league history
- `content/<season>-w<NN>/stories.json`: the week's writing (see `newsroom/STYLE.md`)
- `pipeline/validate.py`: fact-checks every number and time in the stories against the facts
- `pipeline/build.py`: renders the static site into `site/`, including link-preview images
- `newsroom/WEEKLY_RUN.md`: the Tuesday routine

The site is hosted from `site/` (Netlify or Vercel; config for both is included). It is
unlisted: pages carry `noindex` and `robots.txt` blocks crawlers. Change `site_url` in
`config.json` to the live address so preview cards resolve.

Data: Sleeper public API; NFL play-by-play and rosters from nflverse. Fonts: Barlow and Barlow
Condensed (SIL Open Font License).
