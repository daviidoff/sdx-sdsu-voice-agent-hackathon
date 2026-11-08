# Disaster response agent brainstorm and project handoff

Prepared November 8, 2026 for the voice agent hackathon project. This consolidates the wildfire discussion, the earlier hackathon lessons, and the decision to extend the idea to disasters generally.

## Chosen direction

**User decision: pursue the wildfire idea for general disasters.** Build toward an institution-operated agent that discovers needs and resources, talks to people, follows referrals, performs research and computation, and coordinates confirmed assistance. Wildfire remains a reference scenario; flooding and other disruptions can use the same coordination mechanism.

The central loop is:

> A coordinator supplies a goal → agents research initial leads → conversations uncover needs, referrals, and constraints → background agents investigate the new dependencies → the system computes an arrangement → participants confirm commitments → follow-up establishes the outcome.

The user specifically wants Daytona to do substantial work. A fixed contact list and a large batch of calls do not capture the ambition. Each conversation should be able to change the work the system undertakes next.

The choice of disaster response is settled for this brainstorm. The exact demo, implementation architecture, adopting institution, and operational integrations below remain proposals. This handoff does not establish a working integration or a deployed emergency service.

## How the idea developed

The original discussion explored proactive wildfire outreach without requiring affected people to install an app. One early idea was to use park-authorized cameras to identify visitors who might still be inside, find a contact route, and warn them. That exposed a major missing link: observing someone does not establish their identity, telephone number, or present location. Cameras could provide supplementary observations; authorized booking or permit contacts are a more concrete starting point. Unauthorized camera access was excluded.

The discussion then moved toward an authority-operated system: communicate approved local instructions, confirm where people actually are, discover barriers such as limited mobility or lack of transport, and turn those barriers into tracked assistance cases. Operator visibility, takeover, callbacks, and changing orders were part of that concept.

The user's later correction was that judging this solely as an outbound calling product misses the interesting mechanism. Their “worm” analogy described following newly discovered connections: find organizations and locations, reach out, ask about other people or resources, and follow those leads while other agents do useful work in Daytona. The intended mechanism is an expanding investigation with a defined goal, not self-replicating software.

Competition should therefore be assessed against the complete discovery and coordination loop. Existing callers or emergency dashboards do not alone disqualify the idea. Conversely, adding research to calling does not by itself prove novelty.

## Lessons from the earlier hackathon

The Invisible Interfaces retrospective emphasized starting with a concrete blocked situation. Voice should let someone participate when an interface is impractical, or let the system proactively involve people who never joined a shared app. The recipient's answers must affect the next action.

For this project, organizational adoption is the strongest proposed distribution route. An emergency-management team, relief organization, park, or assistance provider adopts the service beforehand. Residents, visitors, suppliers, and local organizations participate through ordinary calls. Do not depend on a distressed person discovering and onboarding to a new consumer product during a disaster.

Compare against a human making calls, SMS check-ins, prerecorded warnings, and existing coordination software. The claimed improvement is making adaptive coordination practical within a staffing and time budget. Call count, a large map, or a pleasant conversation does not establish that improvement.

The event was discussed as an ElevenLabs and Daytona voice-agent hackathon. The target project's README names the SDX SDSU Voice Agent Hackathon. The exact official prompt, judging criteria, and rules for advance work were not captured in the discussion; verify them before treating an internal selection heuristic as an organizer requirement.

## What the wildfire case taught us

The supplied [BBC report about the Bédar fire](https://www.bbc.com/news/articles/cm3vq4wyeld1o) described families challenging the response and officials saying different communities required different instructions, with concerns about panic and congestion. Mobility limitations and a blocked escape road were also discussed. These were attributed accounts, not proof that an AI system would have prevented the deaths.

The resulting design lessons were:

- Adjacent zones can need different actions. Associate instructions with explicit boundaries, effective times, versions, and an authorizing operator.
- A registered address is not a person's current location. Confirm present location before applying location-specific guidance.
- Understanding an instruction and being able to act on it are different. Ask about transport, mobility, companions, language, and practical obstacles.
- Individual arrangements must fit the shared response plan. An apparently reasonable departure can worsen road congestion or conflict with local orders.
- Conditions can change during a call. Revoke stale instructions and identify conversations and commitments affected by the change.
- Finding more needs can overwhelm responders. Every escalation needs an owner, acceptance status, and follow-through.
- An unanswered call remains unresolved. Completing a contact list does not establish that everybody in the area was reached or is safe.

Existing broadcast warnings should proceed independently. [ES-Alert](https://www.proteccioncivil.es/coordinacion/redes/ran/public-warning-system) uses geographic cell broadcast; this does not give our application a list of recipients and dialable numbers. Individual voice calls also do not inherit cell broadcast's resistance to congestion. Never delay the initial authorized warning while collecting contacts or finishing conversations.

## Discovery and contact routes

| Starting point | What it could contribute | What still needs verification |
| --- | --- | --- |
| Authority-authorized resident, subscriber, booking, permit, or service records | A concrete initial contact route | Freshness, permitted use, current location, and missing coverage |
| Campgrounds, hotels, care providers, community organizations | Reach guests or clients; uncover local needs and referrals | Whether the organization can relay a message or share the relevant contact |
| Google Maps and public business or facility directories | Find shelters, transport operators, local coordinators, and potential suppliers | Identity, working number, actual capacity, willingness, and availability |
| Conversations and referrals | Discover people, organizations, resources, and dependencies absent from the initial list | Verify the lead and appropriate contact route before relying on it |
| Official inbound line or callback request | Let people absent from a roster establish contact | Trusted publication of the number and sufficient handling capacity |
| Carrier or dispatch integration | Broader reach and operational handoffs | Actual institutional access and integration capabilities |
| Field teams and local broadcasts | Investigate unresolved areas and reach people without usable phones | Physical resources and coordination with incident command |

Maps and listings provide leads, not proof that a facility has space or a route is safe. A camera observation does not provide a verified telephone number. Population coverage, known contacts, households, and individual people need separate accounting. Data access and recording arrangements must be established with the deploying institution; public visibility alone does not settle permitted use.

## The distinctive coordination behavior

The system should be able to discover that the original request described only one part of the problem. “We need a vehicle” can become “we have a vehicle but need a qualified driver, wheelchair capacity, and a destination willing to receive the group.” Each discovery can create another bounded task.

Useful capabilities to explore include selecting the next question that resolves a bottleneck, following referrals, combining partial offers, identifying incompatible constraints, obtaining conditional commitments, and replanning when somebody cancels. Repeated contacts should be deduplicated, and branches should stop when the objective is met, a budget is reached, or an operator must decide.

For example, a transport provider has vehicles but no drivers. Its manager refers another operator. That operator can provide a driver but identifies an accessibility mismatch. Background agents inspect vehicle specifications and calculate whether a split assignment can satisfy the timing and capacity constraints. The affected parties then confirm the revised arrangement.

The output is an arrangement with accountable commitments and unresolved gaps clearly marked. The agent should never convert a possible lead into a promise of rescue.

## Proposed role of each technology

| Component | Meaningful work |
| --- | --- |
| ElevenLabs | Conduct adaptive conversations; collect needs, constraints, and referrals; explain approved instructions; request confirmations and communicate verified results |
| Daytona | Run research agents and code; inspect permitted websites and documents; extract and reconcile data; check resource compatibility; calculate feasible assignments; investigate newly discovered dependencies |
| Application backend | Own durable incident and task state, authorization, scheduling, retries, duplicate prevention, order versions, commitments, and evidence |
| Operator interface | Show current needs, leads, dependencies, calls, commitments, failures, and unresolved coverage; support intervention and handoff |

[ElevenLabs webhook tools](https://elevenlabs.io/docs/eleven-agents/customization/tools/webhook-tools) can connect conversation-derived inputs to application APIs. [Daytona](https://www.daytona.com/docs) supplies execution environments; it does not automatically supply the planner, shared task state, or operational authority.

The proposed application pattern is to start work with a task ID, expose pending/succeeded/failed status, and confirm external outcomes once even if a request repeats. Slow research can continue between calls. A delayed result must not overwrite a newer request or instruction. Use one SDK generation and pin the version actually tested.

Phone participation requires working telephony setup as well as a voice agent. Human call transfer and full operator monitoring/takeover are separate capabilities to prove. Do not assume a transfer means the AI continues listening or that the entire handoff workflow already exists.

## Proposed coordinator workflow and state

Before incidents, establish contact integrations, instruction templates, escalation destinations, language support, and operational responsibilities. At activation, an operator supplies or imports the incident, relevant zones, current approved instructions and times, the concrete coordination goal, and the responsible response team. A spoken briefing could draft this information for review.

The agent researches initial leads, confirms present conditions by conversation, creates assistance tasks, investigates dependencies, and proposes feasible arrangements. Participants and the responsible operator confirm the required commitments. Follow-up records what actually happened.

Keep these facts distinct in the interface:

- Contact attempted, answered, wrong number, callback pending, or unreachable.
- Current location, confidence, source, and time of confirmation.
- Applicable instruction and version; understanding or an unresolved question.
- Assistance requested, owner assigned, provider contacted, offer received, commitment accepted, and completion reported or otherwise verified.
- Unknown population coverage and known unresolved cases.

Evidence and timestamps should be inspectable. Neither “not ordered to evacuate” nor “answered the phone” means safe. Ordinary maps must not become an autonomous source of evacuation orders or safe-route declarations.

## Proposed hackathon demonstration

**Demonstration criterion:** a conversation reveals an unexpected dependency, the agent creates a new line of work, and that work enables a confirmed arrangement.

The latest suggested story uses a fictitious flood that displaces a group. A shelter has space but the group lacks transport. One provider cannot fully help and refers another operator. The agent follows the referral, uses a Daytona job to check the combined capacity and timing, obtains the relevant confirmations, and calls back with the arrangement. The flood story and an illustrative 18-person group are assistant proposals, not fixed user requirements or real incident data.

Keep the first demo small: one coordinator, a few willing participants, synthetic records, a visible research/computation step, and one completed coordination loop. Clearly label simulated external integrations. Do not send public emergency alerts or contact real affected residents for the demonstration.

Retain the earlier wildfire cases as follow-up scenarios: adjacent zones with opposite instructions, a person at a different location from their record, accessible-transport needs, a wrong number, an unreachable household, a mid-call order change, and operator takeover. A cancellation should trigger replanning and reconfirmation rather than leave an obsolete promise active.

Measure time to a feasible confirmed arrangement, participant and operator effort, accuracy of current instructions, evidence for commitments, duplicate actions, and handling of unresolved cases. Compare with manual coordination. Fabricated routes, unaccepted assistance promises, and known revoked instructions are failed scenarios.

## Competition and adjacent research

The earlier research found substantial overlap. [Genasys](https://www.genasys.com/genasys-protect/communication-zones) covers response zones and evacuation coordination; [Everbridge](https://www.everbridge.com/products/public-warning/) covers multichannel public warning; [Aurelian](https://www.aurelian.com/faq) addresses public-safety call workflows; and [Readyly's Arcadia case study](https://www.readyly.com/case-studies/how-arcadia-kept-residents-safe-and-informed-during-the-los-angeles-wildfires-with-ai/) describes AI access to municipal wildfire information.

[Standard Response](https://devpost.com/software/standard-response) is close hackathon prior art involving zone-triggered calls, household status, assistance coordination, and callbacks. [Safe Path](https://devpost.com/software/safe-path-14cyjp) describes personalized disaster calling with signup requirements. These project descriptions do not establish production effectiveness.

The expanded concept also overlaps with [Veoci mutual aid](https://veoci.com/use-cases/mutual-aid-for-utilities) and research-and-execution products such as [Didero sourcing](https://www.didero.ai/agentic-systems/sourcing-quoting). Investigate whether the specific gap is obtaining changing information and commitments from organizations outside existing platforms, and resolving dependencies that were unknown at the start.

[FEMA's private-sector lifeline guidance](https://www.fema.gov/sites/default/files/documents/fema_restoring-flow-operational-strategies-for-em_012025.pdf) supports the importance of coordination across businesses and sectors. [Reporting from Maui](https://apnews.com/article/f343a8045c87e209df1b84c1443445cb) described volunteers spending hours connecting health officials with a pilot. These support the coordination problem, but do not quantify an addressable calling backlog for our buyer.

Other opportunities discussed were recall tracing through downstream distributors, urgent equipment repair across suppliers and logistics, abnormal-screening follow-up, Medicaid renewal assistance, drug shortages, and critical-facility outage continuity. They helped distinguish evidence of harm from evidence that calls could improve an outcome. **The user subsequently selected general disaster response; these alternatives are background rather than the active product direction.**

## Questions for implementation and validation

1. Which institution adopts this, and which recurring coordination task will it delegate?
2. Which initial contact sources are actually available, and how will referrals be verified?
3. What useful background work can be demonstrated in Daytona within the event constraints?
4. Who authorizes guidance, spending, resource allocation, and final commitments?
5. How will the system recover from unavailable participants, contradictory reports, changed orders, and failed connectivity?
6. What evidence marks a successful arrangement and a completed outcome?
7. Does a real operator's workload show that this saves scarce coordination time without creating a larger escalation queue?

Telephone reachability, trust, carrier capacity, and physical resource availability remain real constraints. As an illustrative calculation from the discussion, 10,000 three-minute conversations require 30,000 call-minutes; even 1,000 continuously occupied slots need at least 30 minutes before dialing overhead and retries. That is arithmetic, not a measured capacity claim.

## Reading provenance

This handoff draws on the user's November 7–8 discussion and the hackathons project's saved research. Supporting local documents are `hackathons/docs/wildfire-response.md`, `hackathons/docs/strategy.md`, `hackathons/docs/voice-opportunity-evidence.md`, `hackathons/docs/voice-agents-preparation.md`, and `hackathons/docs/invisible-interfaces.md` in the sibling project. External links preserve the sources discussed; the implementation should check current API behavior when building.
