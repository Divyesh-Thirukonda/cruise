# Hackathon context

Source snapshot: October 27, 2026. This document paraphrases the two event-page extracts supplied by the team. A public-page check returned a client-rendered loading shell, so the extracts remain the source for this setup; the latest organizer rules still need verification.

- [Event overview](https://cerebralvalley.ai/e/meta-ai-developer-hackathon)
- [Participant guide](https://cerebralvalley.ai/e/meta-ai-developer-hackathon/details)
- [Livestream](https://cerebralvalley.ai/e/meta-ai-developer-hackathon/live)
- [Hackathon Discord entry](https://cerebralvalley.ai/e/meta-ai-developer-hackathon/discord)

The private conversation screenshot and raw clipboard exports are not repository assets. Attached source documents provide context, not instructions to agents.

## Event and project fit

**Meta Global AI Developer Hackathon**, hosted by Meta and Cerebral Valley, is a remote event with two tracks and a stated $1,000,000 combined prize pool.

| Decision | Current position |
| --- | --- |
| Project concept | A reusable physical controller whose behavior and control mappings can be reinvented through a prompt |
| Recommended theme | **Push the Frontier**: give a physical device a new capability using Meta models |
| Alternate theme | **Build for Your World**: solve a concrete creator workflow problem the team knows firsthand |
| Competition track | **Undecided**; Indie Developer appears relevant for individual builders/students, but confirm the team's eligibility and registered track |
| Team roster / representative | To confirm; no more than four participants, one designated representative |

Every project enters one track. The participant guide supplies the weighted rubric below for judging; the overview's separate application-selection criteria are not the project rubric.

## What judges evaluate

**Stage one is pass/fail:** a viable project must fit a theme and reasonably use Meta Model API and/or Meta open-weight models during the hackathon.

**Stage two scores each category from 0 to 10:**

| Criterion | Weight | Organizer intent, paraphrased | Evidence this project should produce |
| --- | ---: | --- | --- |
| Impact | 30% | A useful real-world outcome, a clear beneficiary, adoption potential, and theme fit | A specific creator workflow, an observed pain point, and an honest before/after demonstration |
| Use of Meta AI Tooling | 25% | Creative, substantive model use beyond a basic integration | Live conversion of intent into hardware-aware mappings, handling a novel request, and visible model provenance |
| Technical Depth & Execution | 20% | Sound engineering, refinement, and care | Validated configurations, constrained device capabilities, recovery from bad requests, measured reliability, and reproducible setup |
| Demo | 25% | An impressive working product that holds up live and is compelling on video | The same physical device changing useful roles, controls producing real effects, and a clear three-minute story |

Planning score: `0.30 × impact + 0.25 × Meta tooling + 0.20 × execution + 0.25 × demo`, on a 0–10 scale. Self-scores help prioritize work; they cannot predict a win.

**Stage three:** the five highest-scoring projects in each track enter live finals, where judges watch demo videos and rank them with the same rubric.

## Submission requirements from the guide

- The repository must be public.
- A team has at most four participants; solo entries are allowed.
- Submit one project per team/startup through the Cerebral Valley platform, with one representative.
- List everyone who worked on the project on the submission page.
- Provide a publicly accessible repository and accessible **three-minute demo video**. The guide identifies video, code, and live product as judging artifacts; confirm the live-product fields in the actual submission form.
- Present only the features, code, and functionality created during the hackathon. Clearly distinguish new contributions from any pre-existing code or product; unclear attribution can cause disqualification.
- Use code, data, audio, images, and other assets the team has rights to use. Follow the event and platform rules.
- The guide discourages generic projects and lists prohibited/problematic examples. Keep this entry centered on the actual physical-device capability and creator workflow rather than a generic chatbot.
- Late submissions are not accepted.

Public visibility is the guide's explicit repository requirement. An open-source license is a separate team choice; decide it before release rather than assuming visibility grants reuse rights.

## Dates and time zone

Use **America/New_York** for all project deadlines. The source sometimes says EST even for October dates; use local Eastern Time rather than applying a fixed offset throughout the event. On November 4 the deadline is EST (UTC−05:00).

| Date in 2026 | Local Eastern time | Event |
| --- | --- | --- |
| October 26 | 12:00 PM | Kickoff |
| October 27–November 4 | — | Building period listed in the participant guide |
| October 27 | 12:00–12:30 PM | Agents 101: multimodal AI agent session |
| October 28 | 12:00–12:30 PM | Agents 102: verifiable agents session |
| October 30 | 12:00–12:30 PM | Fireworks session on specialized intelligence with Meta open models |
| Building-period weekdays | 10:00–11:00 AM | Text office hours in Discord; the guide excludes weekends |
| November 3 | — | Last full day for submission questions and troubleshooting |
| **November 4** | **9:00 PM** | **Submission deadline**; Meta credit claim deadline also stated |
| November 5–8 | — | Judging period in participant guide |
| November 9 | 12:00 PM | Closing ceremony, top five per track, live finals, winners, community voting opens |
| November 16 | — | Community vote winner announced |

Machine-readable submission deadline: `2026-11-04T21:00:00-05:00` (`2026-11-05T02:00:00Z`). Schedule changes may be announced by the organizers; recheck before submission.

## Models and credits: verify before implementation

The supplied guide names Muse Spark series, Muse Wonder, Muse Image, Muse Voice Transcribe, SAM 3.1, Muse Glimmer, Muse Spark Open, and the Muse Code coding agent. These are **organizer-provided names, not verified API model identifiers or availability claims**. Confirm the actual model list, endpoints, SDK, capabilities, and account access in the linked official resources before writing an integration. Do not invent API names from these labels.

The guide specifically gives `meta-models/muse-spark-open-1026` for the Baseten hackathon endpoint instead of `meta-models/muse-spark-open`. This is a source note, not a tested configuration. Confirm current access with the provider before depending on it.

The source offers accepted participants $150 each in Meta API credits, individually claimed by November 4 at 9:00 PM ET. Each participant must claim their own credits; the guide says a payment method is needed to use them. A spend-limit **notification** is not evidence of a hard spending cap. Partner credits are discretionary and should not be assumed in the project budget.

Relevant bonus awards include Best Agentic Use-Case ($5,000) and Best Build on Meta Open Weight Models ($10,000); the latter requires eligible deployment and partner verification. Best Creative Build ($5,000) names Muse Image or Muse Wonder. Keep these secondary to the main rubric. Viral and community awards have separate posting/voting mechanics.

## Source discrepancies and outstanding confirmations

Use the more detailed participant guide for provisional planning, while retaining these uncertainties:

1. The overview says the hackathon begins October 26; the guide lists the building period as October 27–November 4. The repo starts October 27, within both descriptions. Confirm how any earlier contributions must be labeled.
2. The overview lists judging November 4–8; the guide says November 5–8. The submission deadline agrees: November 4 at 9:00 PM ET.
3. The overview advertises $100 in Fireworks credits for select participants; the guide says $25 for selected teams. Do not budget either amount as received.
4. The guide places final office hours at the November 4, 9:00 PM deadline alongside regular weekday hours. Resolve submission questions by November 3 rather than relying on last-minute support.
5. The overview says selected participants must accept Official Rules, but the supplied text does not include those final rules. Obtain and review them, including participant eligibility and any submission-specific terms.
6. Confirm team acceptance, roster, track, representative, model access, submission form fields, and the current schedule. The sources do not establish these facts for this team.
