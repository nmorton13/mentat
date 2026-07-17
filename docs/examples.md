# Workflows And Examples

Mentat is deliberately selective. It is not only for research notes or technical
work. It is for thoughts that still have some pull after the moment has passed:
an unresolved question, a feeling you do not want to flatten, a decision whose
context may matter later, or an idea that keeps returning in different forms.

## Capture This, Skip That

Capture thoughts with residue:

```bash
# A question that keeps returning
/capture I keep wondering whether I want a different kind of work, or whether I really want a different way of using the skills I already have

# Something meaningful that you are not ready to resolve
/capture I feel pulled to revisit a box of family stories and help bring them into the world, but I am still conflicted about whether that work is mine to do

# A moment whose feeling matters more than its facts
/capture The early walk was quiet and foggy, with the sun just beginning to come up. I want to remember the feeling of having nowhere else to be

# A tension you recognize in yourself
/capture New AI tools make computers feel fun and open-ended again, but that same possibility can turn into days of rabbit holes and leave me overwhelmed

# A small encounter that stayed with you
/capture I ran into someone I had not seen in years. The conversation was brief, but it reminded me how much a chance interaction can matter even when you may never meet again
```

Usually skip routine exhaust:

- Status updates that matter only today.
- Complete transcripts when only one idea stayed with you.
- Links you cannot yet explain why you care about.
- Tasks already handled well by a task manager.
- Facts that are easy to find again and have not connected to your thinking.

The boundary is personal. The useful test is not "could I save this?" but "is
there a reason I may want to meet this thought again?"

## Starting With Existing Notes

You do not have to begin from an empty history. If you already have Markdown
files, an Obsidian vault, text notes, journals, or exported conversations, an
agent with access to those files and the Mentat CLI can help you identify the
material that still belongs in your active memory.

Start with review rather than automatic capture. Ask the agent to show you a
small set of candidates, preserve your wording where possible, identify the
source file, and avoid duplicates. After you approve the candidates, the agent
can pass them individually to `mentat capture`.

For example:

```text
Review these Markdown notes and identify thoughts that still seem unresolved,
recurring, or connected to my current work. Do not capture anything yet. Show
me the candidates first.
```

```text
Review this Obsidian folder one file at a time. Suggest selective Mentat
captures rather than importing every note. Preserve my wording and include the
source filename in each suggestion.
```

```text
Find repeated questions and themes across these old text files. Prepare a small
set of standalone memories for my review, then capture only the ones I approve.
```

This can give Mentat a useful starting context without turning it into a dump of
everything you have written. Its value comes from returning to a selected
record and noticing what persists, changes, or connects—not from maximizing the
number of memories.

## Return After A Few Days

Mentat becomes useful in the return, not in the volume of capture.

```bash
# See what you deliberately preserved
/latest 15

# Look for recurrence without assuming you already know the theme
/chat what questions have I kept returning to lately?

# Revisit a tension after more experience has accumulated
/search different kind of work
/chat how has my thinking about work and usefulness changed across these notes?

# Bring related fragments together without forcing a conclusion
/synthesize nostalgia and the feeling of early computing
```

## Links With A Reason

`/link` stores a URL and your comment without fetching the page. The comment can
be one sentence about why the source matters, or a longer agent-produced summary
that you reviewed and chose to keep.

```bash
# A short personal reason is enough
/link https://example.com/essay I keep thinking about the author's distinction between doing useful work and proving that you are productive

# An agent can summarize a source before you capture it
/link https://example.com/podcast I listened to this conversation about AI making execution cheaper while judgment and verification become more valuable. What stayed with me is that directing the work may matter more than performing every step.

# Capture your own reaction when the source is secondary
/capture That podcast made me wonder whether taste is really a skill of choosing, or a skill of noticing what does not fit
```

Use a bookmark manager for pages that have not yet earned a reason to remain in
Mentat.

## Unfinished Questions And Decisions

Not every useful capture is a conclusion. Mentat can preserve the shape of a
question while you are still living through it.

```bash
# Several possibilities, none chosen yet
/capture I do not know whether the next chapter is another job, a small business, consulting, or simply becoming more useful to people around me

# Record why a choice feels difficult
/capture Running a local model feels private and almost magical, but the larger hosted models are better at the work I actually ask them to do. I have not settled the tradeoff

# Preserve the emotional part of a practical decision
/capture I want to explore old operating systems because constraints might teach me something, but I also suspect I am trying to recover how computers used to feel

# Return later
/chat which of my unresolved questions have gained evidence, and which ones am I only repeating?
```

Mentat does not need to turn every tension into advice. Sometimes the value is
being able to see that a question has persisted, changed, or quietly disappeared.

## Learning And Open Questions

Capture what changed your understanding, where your understanding still feels
thin, and what you want to test for yourself.

```bash
# A gap you want to understand more honestly
/capture I can follow many statistics and machine-learning ideas conceptually, but I keep wondering what understanding is unavailable to me when I cannot work through the math

# A possible way to learn by doing
/capture Maybe programming in a constrained old environment would help me understand fundamentals that disappear inside modern tools

# A health idea worth carrying forward without turning it into a medical diary
/capture The useful takeaway from learning about walking was that steady, ordinary movement can matter in more ways than I assumed; exercise does not have to be extreme to count

# Find related fragments later
/search learning fundamentals by doing
/chat where do my notes distinguish conceptual understanding from hands-on understanding?
```

## Moments, Patterns, And Self-Observation

Some memories matter because they show how you move through the world rather
than because they support a project.

```bash
# Notice a recurring source of energy
/capture Spring and summer mornings make me want to be outside before the day starts. Part of the feeling is knowing the light is temporary

# Notice your natural working style
/capture I tend to begin with a giant idea, make a mess, and then keep chipping away until the real shape appears. The plan often arrives through the work rather than before it

# Preserve ambivalence instead of cleaning it up
/capture I love having many things I could build, read, or explore. I also know that possibility itself can become a way of avoiding a choice

# Ask Mentat to reflect the selected record back to you
/chat what seems to give me energy, and what repeatedly turns that energy into overload?
```

## Podcast And Reading Notes

Do not save every point. Keep the idea that stayed with you and your response to
it.

```bash
# The source, the idea, and your reaction
/capture I listened to a conversation about automation creating more work around judgment, review, and deciding what is worth doing. I liked the idea that better tools expand ambition instead of simply reducing effort

# A question opened by the source
/capture The physics discussion kept returning to unification. I wonder whether I am drawn to unified explanations because they reveal something real, or because they make complexity feel manageable

# A sentence that continues working on you
/capture I ordered a book about the writing life because I want to spend more time with the tension between wanting to write and actually living as a writer
```

## Capture Through An Agent

Mentat can be the durable memory behind a conversational or voice-capable agent.
For example, you might talk through an idea with Codex during a walk and then
say, "Capture this in Mentat." The same workflow can work with any agent that
has permission to run the Mentat CLI.

The useful boundary is still your decision to capture. The agent may preserve
what you said directly, or prepare a shorter note when you explicitly ask it to
summarize first.

```text
You: I keep circling around whether I want a different job or a different way
     to use the skills I already have.

You: Capture this in Mentat.
Agent: [runs Mentat capture with your note]
```

The underlying command for a short note is:

```bash
uv run mentat capture "I keep circling around whether I want a different job or a different way to use the skills I already have."
```

For a longer voice note, transcript, or agent-prepared summary, the agent can
pass the text through standard input:

```bash
uv run mentat capture -
```

This keeps the roles clear: the conversation helps you develop the thought,
you decide that it is worth keeping, and Mentat preserves it for later return.

The agent can also be a conversational way back into Mentat. You can ask what
Mentat has to say about one topic or how two recurring threads connect:

```text
You: What does Mentat think about nostalgia and older computers?
Agent: [queries Mentat and returns a synthesis of your memories]

You: What connections does Mentat see between learning fundamentals and working
     with constrained systems?
Agent: [queries Mentat with both ideas and returns the result]
```

The underlying commands are ordinary agent-friendly chat calls:

```bash
uv run mentat chat "what have I captured about nostalgia and older computers?" --json
uv run mentat chat "how do my notes connect learning fundamentals with constrained systems?" --json
```

"What does Mentat think?" is convenient conversational shorthand. The response
is a synthesis of the memories you chose to preserve, not a complete account of
your life and not a set of beliefs held by Mentat itself.

## AI Responses As References

`/save` can keep an especially useful AI response, but saved AI output remains a
separate reference archive. Mentat does not feed it back into ordinary memory
context as evidence of what you think.

```bash
/chat help me compare the different ways I have described nostalgia for older computers
/save

# Find saved AI references explicitly
/search ai response nostalgia computers
```

Capture the response's conclusion in your own words when it genuinely changes
your thinking. That new note can then become part of normal memory context.

## Command Combinations

```bash
# Follow an unresolved personal thread
/search family stories
/view 2
/chat how has my thinking about revisiting and editing family stories changed over time?

# Move from a moment to a broader pattern
/search morning walk
/synthesize attention light and solitude

# Revisit learning across different subjects
/chat where have I wanted to move from conceptual understanding to direct practice?
```

## Working Rhythm

1. Capture sparingly when a thought has consequence, recurrence, or unresolved energy.
2. Include why a source, event, or passing observation matters to you.
3. Let tags, entities, and connections emerge after capture.
4. Return after enough time has passed for recurrence and contrast to become visible.
5. Treat Mentat's answers as analysis of the memories you selected, never as a complete account of your life.
