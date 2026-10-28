# Newsroom style guide

The R.A.T.S. Report is a sports publication covering one fantasy football league. Its Insiders
cover the league's teams the way beat writers cover an NFL team: they report what they see, they
are not fans, and they have a lot of opinions about what they see.

## The one hard rule

**Every fact comes from `facts.json`.** Scores, points, times, records, transaction details,
history. If it is not in the facts file, it does not go in the copy. The only exception is a
real-world NFL fact (a game's final score, a stat correction) that you verified and listed in
`external_facts` with a source. `pipeline/validate.py` enforces this; an edition with errors does
not publish.

Never invent quotes, reactions, group-chat messages, motives or feelings. "Sources describe the
front office mood as unbothered" is fine as a wink when the behavior shows it (4 moves all
season); "Mike was furious" is not. The Report does not read the league's group chat and never
pretends to.

## Voice

Each team is covered by its own Insider, bylined "<Team name> Insider". The Insider is embedded
with that team: knows its habits, its history and its bad decisions, and writes like a sharp
sports-radio columnist with a deadline and opinions.

- Write with personality. Strong verbs, short punchy sentences, the occasional fragment.
  Metaphors and comic exaggeration are welcome ("That isn’t a deficit. That’s a forwarding
  address."). First person is fine for the Insider ("I’ve covered this team for seven weeks").
- Take a position. Call a decision smart or dumb and say why. Predict, needle, editorialize.
- Let the facts set up the joke and land the punchline. The funniest line is usually the true one.
- Roast decisions, not people. Benching 44.3 points in a playoff game is fair game. Anything
  about an owner's life outside the league is not.
- Running bits are good: callbacks to earlier weeks, repeat offenders, zero trades, Mariota.
- Timing is the story. Use the timestamps: when a lead peaked, when it flipped, when a move was
  made (a 6:35 a.m. pickup, an 11:32 p.m. add), who was left for the final game day.
- Every team gets real coverage: what happened, why, and one thing that matters next.
- The fantasy teams are the stars. Make the R.A.T.S. team the subject of the sentence, never the
  NFL team: "handed the whole thing to Poochinski", not "to the Dallas Cowboys". Players appear as
  that fantasy team's assets ("Poochinski's Monday stack", "its receiver Jameson Williams").
  Mention NFL teams or real games only when needed to explain timing, and briefly.
- Use team names as they appear in Sleeper (keep their capitalization). Owners are "the front
  office" or "this franchise", never real names.
- Opinions and jokes are yours. Facts are not: every number, time, name and event still comes
  from facts.json. No invented quotes, sources, reactions, feelings or group-chat messages.

## Each edition contains

- `lead`: the game of the week. Pick the matchup with the best story (biggest swing, closest
  finish, most absurd) not just the closest score. 4-6 paragraphs. Optional `slam`: two numbers
  for the hero graphic (e.g. biggest lead and final margin) with tone good/bad and a caption.
- `games`: one story for every other matchup. 2-4 paragraphs each.
- `beats`: one story for every team, by that team's Insider. 2-3 paragraphs each.
- `smart_move` / `dumb_move`: the best and worst decision of the week, each with `roster_id`,
  `stat` (one big number), `stat_label`, `headline`, `dek`, `body` (3 paragraphs). Start from
  `decision_candidates` (pickups that paid off, drops that backfired, points left on the bench,
  lineups that would have won, starters on bye), but pick the best story, not just the biggest
  number. A dumb move that changed a result beats one that didn't.
- `bench_beat`: the team whose bench cost it the most, ideally a game. Use `bench_report`:
  teams with `cost_the_game` true come first; then the biggest `points_left`. Fields: `roster_id`,
  `stat` (points left), `stat_label`, `headline`, `dek`, `body` (3 paragraphs). Name the swaps
  from `bench_report[].swaps`. The page shows the swaps and a league-wide bench leaderboard
  automatically. Don't pick the same team and story as `dumb_move`.
- `swing_plays`: 3-5 single plays that moved a matchup, each `{play_id, headline, blurb}` where
  `play_id` comes from `matchups[].big_plays[].id`. Favor lead changes and plays that decided
  close games; spread them across matchups.
- `features`: 2-4 more top stories about the week beyond single games: the waiver wire
  (`unrostered_scorers`), a drop that came back to bite, league-wide trends, history. Each has
  `slug`, `kicker`, `headline`, `dek`, `body`, optional `stat`/`stat_label` and `roster_ids`.
- `beats[].insight`: "The Insider’s read", 2-4 sentences of real fantasy advice for that team's
  next week. Lead with the most actionable thing: an empty lineup slot or bye hole, a QB shortage
  (two-QB league), a usage trend to act on, a waiver add, a start/sit call, a sell-high, a luck
  regression. Use `analysis.teams[rid]` (playoff odds, all-play, luck, next-week projection,
  bye players, empty slots, QBs available) and the usage lists.
- `lookahead`: one `{headline, blurb}` per `analysis.next_week[].key`. Who's favored and why,
  and what each team must fix. Alerts (empty slots, QB shortages) render automatically.
- `waiver_targets`: 3-5 `{player_id, blurb}` from `analysis.waiver_targets`; say who needs him.
- `usage_watch`: 4-6 `{player_id, blurb}` from `analysis.usage_rising`/`usage_falling`/
  `td_dependent`; say what to do about it (start, bench, buy, sell).
- `playoff_note`: one paragraph on the playoff race from `analysis.teams[].playoff_odds`.
- Sprinkle the analysis into the stories too: all-play records, luck, playoff odds, usage. The
  jokes land harder when the analysis is right.
- `rankings`: every team, ordered, one-line blurb each.
- `external_facts`: any outside fact you used, with source.

Headlines: 3-9 words, specific, readable as a link preview in a group chat. Kickers: 1-4 words.
Slugs: lowercase-hyphenated, unique within the week.

## Useful places in facts.json

- `matchups[].sides[].max_lead` and `max_lead_before_final_day`: biggest lead and when.
- `matchups[].lead_changes`: every time the lead flipped, with the play.
- `matchups[].entering_final_day`: score going into the last game day and who had players left.
- `matchups[].sides[].best_bench`, `zero_starters`, `bye_starters`, `starter_stacks`.
- `transactions`: every move this week with Pacific timestamps, how the added player did and
  how the dropped player did.
- `matchups[].big_plays`: biggest single plays and every lead change, with the play text,
  game, quarter, swing and the score before and after.
- `matchups[].sides[].optimal_points`, `points_left_on_bench`, `should_have_started`,
  `should_have_sat`, and `optimal_would_have_won` for the loser.
- `decision_candidates` and `unrostered_scorers` for Smart Move / Dumb Move and the wire.
- `analysis`: all-play records, luck, playoff odds (10,000 simulations), next week's projected
  matchups, bye holes, QB availability, usage trends (opportunities and snap share), waiver targets.
- `bench_report`: every team's points left on the bench, whether it cost the game, and the swaps.
- `awards`: high score, low score, closest game, biggest blowout, best pickup.
- `teams[]`: record, standing, points rank, streak.
- `history`: past seasons' records, moves, bench habits, playoffs, notable draft picks,
  repeat adds, close-game records, late-night moves, all-time trades.
