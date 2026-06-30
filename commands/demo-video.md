---
description: Make a narrated demo video of an app using the demo-creator agent
argument-hint: <project name> <app URL>
---

Launch the **demo-creator** subagent to produce a short, polished, narrated demo
video that walks through every feature of the target below.

Target: $ARGUMENTS

First, establish the **project name** and **URL** (ask if either is missing), then
create a single project folder `<DEMOS_ROOT>/<project-slug>/` (default
`%USERPROFILE%\Demos` on Windows, `~/Demos` elsewhere; override with
`DEMO_OUTPUT_DIR`) and write `project.json` there. All shots, audio, and the
finished `<project-slug>-demo.mp4` go in that one folder.

Before generating any audio, the agent must confirm with me:
1. the **ElevenLabs voice** (offer my cloned voice), and
2. the **narration language**.

Then: capture one clean screenshot per feature, write one short narration line
per shot, generate the per-shot voice-over via the **elevenlabs-dialogue** skill,
and assemble the final `mp4` with ffmpeg — verifying that what is shown matches
what is said in every shot. Open the result when it's done.

If no target was given above, ask me which app/URL to demo before starting.
