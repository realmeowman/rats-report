# Newsroom style guide

The R.A.T.S. Report is a sports publication covering one fantasy football league. Its reporters
cover the league's teams the way beat writers cover an NFL team: they report what they see, they
are not fans, and they are funny because the facts are funny.

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

- Deadpan beat writer. Short declarative sentences. Let the number land the joke.
- Roast decisions, not people. Benching 44.3 points in a playoff game is fair game.
  Anything about an owner's life outside the league is not.
- Every team gets real coverage: what happened, why, and one thing that matters next.
- Timing is the story. Use the timestamps: when a lead peaked, when it flipped, when a move was
  made (a 6:35 a.m. pickup, an 11:32 p.m. add), who was left for the final game day.
- Use history to build running storylines: repeat offenders on the bench, players added
  again and again, zero trades, playoff ghosts.
- Use team names as they appear in Sleeper (keep their capitalization). Owners are referred to
  by team name or "the front office", not by real names.
- Plain words. No em-dash asides. No "not X, but Y". No hype words.

## Each edition contains

- `lead`: the game of the week. Pick the matchup with the best story (biggest swing, closest
  finish, most absurd) not just the closest score. 4-6 paragraphs. Optional `slam`: two numbers
  for the hero graphic (e.g. biggest lead and final margin) with tone good/bad and a caption.
- `games`: one story for every other matchup. 2-4 paragraphs each.
- `beats`: one story for every team, by that team's reporter. 2-3 paragraphs each.
- `rankings`: every team, ordered, one-line blurb each.
- `external_facts`: any outside fact you used, with source.

Headlines: 3-9 words, specific, readable as a link preview in a group chat. Kickers: 1-4 words.
Slugs: lowercase-hyphenated, unique within the week.

## Useful places in facts.json

- `matchups[].sides[].max_lead` and `max_lead_before_final_day`: biggest lead and when.
- `matchups[].lead_changes`: every time the lead flipped, with the play.
- `matchups[].entering_final_day`: score going into the last game day and who had players left.
- `matchups[].sides[].best_bench`, `zero_starters`, `bye_starters`, `starter_stacks`.
- `transactions`: every move this week with Pacific timestamps and how the added player did.
- `awards`: high score, low score, closest game, biggest blowout, best pickup.
- `teams[]`: record, standing, points rank, streak.
- `history`: past seasons' records, moves, bench habits, playoffs, notable draft picks,
  repeat adds, close-game records, late-night moves, all-time trades.
