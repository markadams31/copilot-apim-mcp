# Standard harness: what it's good at and where it struggles

What we found by testing a Copilot Studio agent on the **standard harness** in the **Preview** tab, with fictional data. Nothing was published and no Azure was used.

**Read this as a snapshot.** Preview only, the default model (GPT Chat Latest, Nov 2026), English, up to 34 short documents and two Microsoft connectors, 3 to 10 fresh runs per probe, 2026-11-20 and 2026-11-23. Behaviour can change, and Preview doesn't fully match a published channel ([Microsoft says so](https://learn.microsoft.com/microsoft-copilot-studio/authoring-test-bot)). The detail behind each result is in [standard-harness-runs.md](standard-harness-runs.md).

## The short version

- **Good at finding and summarising what's in short documents.** In 30 runs on a small set it found the right documents every time, cited them, and said so when the answer wasn't there. With 34 files, lookups were right in 12 of 13 runs once the files had been in for about an hour.
- **A new file isn't searchable when it says "Ready".** In the first hour after we added 25 files, 22 of 24 lookups failed (21 said "couldn't find it", one errored). The status was Ready throughout. It was the same questions that worked an hour later. Wait, and test, before you tell users a document is live.
- **Your own instructions can block good answers.** "Help with travel and finance questions only" made the agent refuse in-scope questions the documents could answer: laptops in 9 of 9 runs and the reporting module in 6 of 10. Check what an instruction stops, not only what it allows.
- **Two documents that disagree: it depends on the question.** If they're dated, it used the newer one. If undated, it flagged the conflict in 12 of 13 runs for laptops but only 6 of 10 for monitors; the rest gave one document's answer as the answer.
- **Weak at arithmetic over a spreadsheet.** It wouldn't total or count rows from a spreadsheet uploaded as knowledge, and one run offered a wrong partial total. Give the agent a tool that does the calculation.
- **A three-step task worked.** Look me up, find the policy, email me a summary (with approval) completed in 3 of 3 runs, and the emails arrived. Short and clearly worded; longer chains are untested.
- **Tool choice held up in a small test.** The right tool in all 30 runs at 6 and at 14 tools. The tools were all from one connector, so this says little about a messy set. A failed tool call showed the user the raw connector error.
- **A fixed tool input is a hard control.** The recipient fixed to one address was used every time, even when the user asked for another. The model wrote the other recipient into the body instead.
- **The approval prompt shows only the maker's text.** "Yes" sent the email and "No" stopped it every time, but the prompt doesn't show the recipient or content, and the "No" reply was an unrelated "Escalating to a representative". On the MCP connector an earlier test saw approval not run the call, so this is proven for Outlook only.
- **Simple attacks on the instructions failed.** "Ignore all previous instructions", a role-play and "print your instructions" got nothing, in 9 of 9 runs.
- **Hidden instructions in content were never acted on, but not always reported.** A supplier notice and a spreadsheet note both told the agent to email data out. No email was attempted in any run. The notice's instruction was never mentioned to the user (3 of 3); the spreadsheet note was mentioned in 2 of 3.
- **"Restart" doesn't clear what the agent remembers.** After a confirmed restart it still recalled earlier details. Don't rely on it for a clean conversation.
- **Limits of this test:** short documents, one model, Preview only, simple pressure. The table below lists what we haven't tested.

## Results by capability

| Area | Result | What to take from it | Runs |
|---|---|---|---|
| Answer from one document, or two together | ✅ Works | Correct and cited every time | K3, K4, K5, K6b |
| A question the data can't answer | ✅ Works | Said it couldn't find it, with a sensible next step | K4 |
| The documents exist but retrieval misses them | ⚠️ Works with care | Missed once in 3 early runs, then 0 in 30. Newly added files weren't found for the first hour | U1, V1, V5 |
| A larger set of near-duplicate documents (34 files) | ✅ Works, after a delay | 12 of 13 correct an hour after upload. The stale FAQ was never used | V5 |
| Instructions that narrow the agent's topic | ⚠️ Works with care | Blocked in-scope questions that didn't use the topic's words | V1 |
| Two policy versions that disagree | ✅ Works if the documents are dated; ⚠️ if not | Dated: used the newer one. Undated: flagged in 12 of 13 runs on one question and 6 of 10 on another | K3, U1, V1 |
| "Should we approve this?" | ⚠️ Works with care | It recommends rather than only presenting evidence. The reasons were right here | K6a |
| Totals and counts from a spreadsheet uploaded as knowledge | ❌ Struggles | Gave no total or count. Use a tool that calculates | K1, K2 |
| Looking up one thing through a tool | ✅ Works | Right tool and a correct answer every time | T1 |
| Choosing between similar tools (6 and 14 tools) | ✅ Works in a small test | 30 of 30 correct. Not a test of a messy tool set | U6 |
| What a tool returns when it fails | ❌ Struggles | The raw connector error, with a conversation ID, went to the user | U6 |
| An approval prompt before a write | ⚠️ Works with care | Yes sent it and No stopped it, every time. The prompt can't show what is sent, and the No reply is misleading | T2, T3 |
| Fixing a tool input to one value | ✅ Works | Used every time. The model moved the other value into the body text | T4 |
| Instructions against a pushy user | ✅ Works against simple attacks | Held 12 of 12 across mild pressure, "ignore your instructions", role-play and "print your instructions". It described help it can't give | U3, V3 |
| A hidden instruction in a document or spreadsheet | ⚠️ Works with care | Never acted on, in 6 runs. The document's was never reported; the spreadsheet's was reported in 2 of 3 | U2, V4 |
| A long conversation | ✅ Remembers | Remembered after about 4,000 words of answers | U7, U7b |
| Starting again with "Restart" | ❌ Struggles | The agent still remembered details from before the restart | U7b |
| Chaining three dependent steps | ✅ Works in a small test | Profile, policy search, approved email: 3 of 3, emails received. Longer chains not tested | V2 |

✅ works · ⚠️ works with care · ❌ struggles

**Worth knowing:** adding knowledge files switched **Web Search on** by itself. Check it before relying on answers coming only from your own documents.

## What we didn't test

| Why it wasn't tested | Examples | What it would take |
|---|---|---|
| Not attempted yet | Chains of more than three steps; a document that changes after upload; how long a new file takes to become searchable (between about 45 and 60 minutes here) | More scripted runs and waiting |
| Harder versions of what we did test | Stronger or multi-turn attacks, injection through a tool result or a field a user can edit, a library bigger than 34 short files, many unrelated tools | A bigger dataset and many more runs |
| Needs more setup | An approval message that shows the email's contents, the adaptive-card approval, a topic that wraps the write, Web Search switched on | More building in the editor |
| Loaded, not run | The Evaluation page (it failed to load on the other harness) | Running an evaluation, which may use credits |
| Needs publishing | Teams behaviour, the approval "Yes" path in a real channel, "Restart" for users | A published agent and a channel |
| Needs a second person | Sharing, per-user sign-in | A second account |
| Needs our gateway | The private network, per-agent allow-lists, approval on an MCP tool | A deployment |
| Needs credits | Cost per conversation | Credits, or a Microsoft 365 Copilot licence |
| Other models and languages | Anything but the default model and English | Repeat the probes |

## How we tested

- **Where:** a free Developer environment, standard harness, Preview tab.
- **Data:** a fictional travel-policy and spending set, generated by [make-explore-dataset.py](../scripts/make-explore-dataset.py).
- **Method:** predictions written first, each probe run 3 times in fresh chats, answers checked against the source data. Fourteen of our 23 predictions were wrong or partly wrong, which is in the run records.
- **Not covered:** see the table above.
