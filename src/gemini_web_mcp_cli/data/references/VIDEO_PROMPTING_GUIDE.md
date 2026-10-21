# Gemini Omni — Video Prompting Guide

Reference guide for generating and editing cinematic videos using Gemini Omni (the Veo 3.1 video engine powering Gemini's native video generation). Distilled from Google DeepMind's official [Gemini Omni Prompt Guide](https://deepmind.google/models/gemini-omni/prompt-guide/), industry cinematography standards, and deep developer testing.

**Hard limits:** Generates highly fluid high-definition video with integrated audio. Video generation takes **1–2 minutes** (polling-based workflow). Requires BotGuard tokens via Chrome browser login. Maximum performance is unlocked by stacking multimodal inputs (video, image, audio, and text).

---

## 1. Model Overview

Gemini Omni is not just a video generator—it is a multimodal world model. Unlike classical engines, Omni reasoning-links your visual ideas, texts, and sound environments together.

| Feature | Specification | Developer Notes |
|---------|---------------|-----------------|
| **Engine** | Gemini Omni (Veo 3.1) | High-fidelity fluid motion, physics realism, complex text rendering. |
| **Models** | Flash (default), Pro, Lite, Thinking | Select with `-m pro` etc. Pro/thinking use the higher-quality engine. |
| **Orientation** | Landscape 16:9 (default), Portrait 9:16 | Select with `-O portrait` for Shorts/Reels/TikTok. |
| **Duration** | Up to 10 seconds (native) | Can be directed to fit specific timing structures. |
| **Audio** | Native Audio Sync | Soundscapes, effects, and music beats are generated in perfect sync. |
| **Interface** | CLI (`gemcli video`), MCP | Wrapped in a background polling architecture (`hNvQHb` RPC). |
| **Auth** | Token Factory | Requires active Chrome session with full BotGuard challenge solving. |

---

## 2. The Core Paradigm Shift: Intent over Prescription

Classical video models (like raw Veo) required developers to write exhaustive, pixel-by-pixel spatial descriptions. 

**Gemini Omni operates on World Knowledge.** Because it understands physics, history, and cultural context, you describe your **intent and aesthetic direction**, and let the model reason out the mechanical details.

* **Veo Style (Avoid):** `A green tennis ball drops from exactly 2 meters height. It accelerates down at 9.8m/s^2, hits the grey concrete court, squashes slightly on impact, bounces up to 1.2 meters, spins counter-clockwise at 50rpm...`
* **Gemini Omni Style (Prefer):** `A realistic, slow-motion shot of a green tennis ball falling onto a rain-slicked concrete tennis court, bouncing once with accurate gravity and scattering water droplets in a low-angle close-up.`

---

## 3. The 6-Dimension Prompt Framework

To get complete control over your video output, structure your master prompts using these six dimensions:

```
[Subject/Character] + [Action] + [Location/Context] + [Lighting] + [Style/Aesthetic] + [Cinematography/Camera]
```

### Prompt Construction Template

Use this blueprint when writing high-end video prompts:

```
Subject:
[Focal character or object. Describe materials, textures, colors, and dynamic properties.]

Action/Interaction:
[What the subject is doing. Detail micro-movements or interactions with the surroundings.]

Location/Context:
[The background environment, geographic context, or atmospheric backdrop.]

Lighting:
[Direction, quality, color, and behavior of light sources. Be specific about reflections and shadows.]

Style/Aesthetic:
[The visual language: eg., "3D translucent glass style," "contemporary flat-media stipple risograph," "retro 16mm film."]

Cinematography:
[Camera setup, lens type, framing, camera movements, and timing/pacing instructions.]
```

---

## 4. Cinematography & Camera Direction

Omni respects precise industry camera terms. By using these keywords, you prevent generic pan-and-scan camera movements and achieve professional cinematic framing.

### Camera Motions & Angles
* **"Oner" or "One continuous shot":** Generates a smooth, single-camera take without cuts, maintaining temporal consistency across the timeline.
* **"Static" / "Locked off" / "Fixed camera":** Keeps the tripod perfectly still, allowing only the subjects in the scene to move. Crucial for high-end character edits.
* **"Push in" / "Punch in":** Smooth, forward camera translation toward the focal subject.
* **"Dolly zoom":** Performs a classic vertigo effect (camera dollies backward while lens zooms in, distorting the background perspective).
* **"Tracking shot":** The camera glides parallel to a moving subject, matching its velocity.

### Camera Styles
* **"Natural smartphone zoom":** Emulates handheld, slightly shaky zooming, mimicking casual viral footage.
* **"Film camera style":** Adds authentic anamorphic lens flares, slight gate weave, and deep-focus grain.
* **"Webcam style":** Creates slightly wide, low-angle, fixed-lens indoor security or desktop camera perspective.

#### Cinematography Example
> **Prompt:** `A low-angle close-up tracking shot of vintage leather boots walking along a wet cobblestone street at night. The camera starts focused on the boots, then performs a rapid tilt up to a medium shot of a detective in a heavy wool coat, before slowly widening. Cinematic film camera style, heavy rain, mist catching the yellow glow of gas lamps.`

---

## 5. Conversational & Iterative Video Editing

One of Omni's greatest features is its conversational state. You do not need to rewrite your entire prompt to make changes. You can modify elements sequentially, while keeping the rest of the clip locked.

### Iteration Rules
1. **Change one variable at a time:** Do not ask to change the character, background, and lighting all in one prompt.
2. **Use "Keep everything the same" or "Preserve" instruction:** Reinforce elements that you want the model to lock.
3. **Describe the delta precisely:** Clearly define what goes out and what comes in.

```mermaid
graph TD
    A[Generate Base Video] --> B[Review Composition]
    B --> C[Prompt: "Change butterfly to bee. Keep everything else the same."]
    C --> D[Review Delta]
    D --> E[Prompt: "Change the bee into fireflies. Keep the environment and violin movement."]
    E --> F[Final Masterpiece]
```

### Conversational Edit Sequence
* **Turn 1 (Base):** `Generate a video of a gorgeous garden scene with a glowing orange butterfly landing on a blooming flower.`
* **Turn 2 (Subject swap):** `Change the butterfly to a bee. Keep the exact background, lighting, and camera angle the same.`
* **Turn 3 (Subject evolve):** `Change the bee into a small swarm of glowing fireflies flickering in the twilight.`
* **Turn 4 (Camera shift):** `Change the camera angle to be a close-up, panning slowly to reveal the fireflies rising into the trees. Keep the environment identical.`

---

## 6. Text Rendering & Kinetic Typography

Gemini Omni excels at rendering highly stylized, readable, animated text inside video streams. It can sync text animations to a specific pacing rhythm.

### Kinetic Typography Rules
* **Enclose words in quotes:** Use double quotes for the target text.
* **Specify word-by-word flow:** Tell the model to display words sequentially.
* **Define text-specific styling:** Describe fonts, colors, and motion styles per phrase.

#### Typography Example
> **Prompt:** `word by word, one word on the screen at a time: "Did", "you", "know", "that", "this", "model", "can", "do", "pretty", "good", "text!?". Each word appears in a different animated style (crayon, neon glowing, bold sans-serif, metallic chrome) with perfect pacing to a fast hip-hop rhythm. Dynamic sizzle reel aesthetic, dark background.`

---

## 7. Multimodal Input Stacking

You can feed Gemini Omni multiple inputs simultaneously. Stacking `<video>`, `<image>`, `<audio>`, and text prompts yields unparalleled control over consistency.

### Input Stacking Blueprint

```
[Target Action / Logic] + [Video Reference Tag] + [Visual Theme / Image Reference Tag] + [Temporal Sync / Audio Reference Tag]
```

#### Multimodal Examples
* **Visual Form + Music Sync:**
  `The birds from <video> loosely form the imperfect shape of a stylized falcon based on the structure of <image>. They move in perfect sync to the rising tempo of the music from <audio> and dissipate into ashes as they fly away.`
* **Style Transfer:**
  `Apply the structural layout and kinetic motion from <video>, but stylize the environment and characters to match the exact aesthetic, HSL color palette, and textures of the painting in <image>.`

---

## 8. Style Transfer & Consistency

Omni supports seamless stylistic transformations. You can shift a realistic reference video into complex artistic aesthetics while retaining identical temporal motion and spatial layouts.

### Premium Stylistic Targets
* **Tactile Risograph:** Limited three-color palettes (neon pink, cyan, yellow), grainy stipple gradients, intentional paper registration overlays.
* **3D Translucent Glass:** Complex light refractions, caustic patterns, soft internal sub-surface scattering glows, minimalist studio setting.
* **Graphite Pencil Sketch:** Cross-hatching, varying line weights, 12fps "line boiling" effect on granulated paper to emphasize hand-drawn textures.
* **Waxy Crayon:** Playful waxy strokes, hand-drawn character designs, heavily textured watercolor paper background.

#### Stylistic Progression Example
> **Prompt:** `Create a four-part stylistic progression of the video reference that begins with a vibrant colored crayon aesthetic, featuring rich, waxy, textured strokes and playful character designs. Transition seamlessly into a graphite pencil sketch on textured paper, utilizing cross-hatching and a 12fps line boiling effect. Next, morph into a hyper-realistic 3D translucent glass style with caustic refractions and soft internal glows. Conclude with a tactile risograph print look using neon pink and deep navy stipple shading.`

---

## 9. Visual Storyboards

For long-form narratives, you can upload a storyboard matrix (a grid image depicting the sequence of actions) and instruct Omni to stitch it into a continuous, timed video clip.

### Storyboard Prompt Rules
1. **Define the grid layout:** Tell the model where the story starts and how it flows (e.g., "starting top-left, moving right, then down").
2. **Assign the timing:** Set the overall duration of the final clip.
3. **Enforce cinematic transition:** Specify seamless interpolation between key panels.

#### Storyboard Example
> **Prompt:** `Generate a cinematic video sequence based on the uploaded storyboard grid. Follow the story exactly in order starting from the top-left panel, proceeding row-by-row. Interpolate the motions smoothly to tell the entire story in 10 seconds. Keep the visual style, character model, and lighting consistent with the storyboard panels.`

---

## 10. Prompt Recipes by Category

### 1. The Quantum Explainer (Flat-Media Flat Vector)
```
Explain the difference between regular computing and quantum computing. Visualize this sentence using a contemporary flat-media style that blends minimalist vector shapes with rich organic textures. The aesthetic is defined by a high-contrast, "electric" color palette of neon pinks, cyans, and limes set against a deep navy background. A hallmark of this style is the use of stipple shading and grainy gradients, which adds a tactile, risograph-like quality to the otherwise simple geometric forms. By combining sharp edges with softened, speckled transitions, the illustration achieves a playful, editorial feel.
```

### 2. Kinetic Text Sizzle Reel
```
Kinetic typography animation. Solid black screen. Text flashes word-by-word: "BEYOND", "THE", "HORIZON", "LIES", "THE", "FUTURE". Each word stays on screen for exactly 0.5 seconds, matching the tempo of a driving synthesizer beat. "BEYOND" is rendered in massive bold white sans-serif; "THE" is small and centered; "HORIZON" explodes outward in a digital glitch neon-cyan pattern; "LIES" melts away as liquid chrome; "FUTURE" shines with lens flares in a golden-hour gradient. Highly modern, high-contrast sizzle reel.
```

### 3. The Cinematic Oner (Noir Mystery)
```
A continuous 8-second cinematic tracking shot (oner) through a rain-slicked neon alley in Tokyo. The camera glides forward at chest-height behind a detective in a dark trench coat. Puddles on the cobblestones reflect flickering amber and pink neon signs. A steam vent to the right blows white fog across the frame, catch-lighting the scene. The detective stops, looks up, and a subtle lens flare sweeps across the screen. Cinematic anamorphic lens, shallow depth of field, slow-motion fluid movement.
```

### 4. Interactive Music Sync (Building Beats)
```
Input video: A wide shot of an urban cityscape at dusk, sky painted in deep purple and amber. 
Prompt: Modify this video so that the lights of the skyscrapers start turning on and pulsing in perfect rhythm and sync with the deep bass beats of the attached soundtrack. With every high snare hit, add subtle neon orange flashes echoing across the windows. Maintain identical camera placement and city architecture.
```

### 5. Deep Space Explorer (Sci-Fi Cinematic)
```
A premium cinematic science-fiction tracking shot of the "Apex-01" starship. The spacecraft has a sleek, aerodynamic body made of brushed carbon fiber with glowing neon blue accent lines running along its hull. It glides gracefully through a deep violet planetary nebula, leaving a trail of shimmering cosmic dust in its wake. The camera starts with a locked-off side profile, then smoothly pans and pushes in to a dramatic over-the-shoulder shot behind the starship as it heads toward a bright stellar flare. Photorealistic reflections, caustic stellar light, extreme visual depth.
```

### 6. Interactive Character Consistency (Astronaut Swap)
```
Input video: An astronaut walking slowly on a desolate Martian desert.
Prompt: Edit this video keeping everything completely identical. Change the astronaut into a large, shimmering, translucent sea anemone that moves its tentacles in fluid rhythm with the walking motion. The anemone should project a soft neon blue internal glow that reflects realistically on the orange sand below.
```

---

## 11. Common Mistakes & Pitfalls

| What Fails | What Works (Instead) |
|------------|----------------------|
| **Vague Adjectives:** "epic video, insane quality, beautiful effects, highly detailed." | **Visual Modifiers:** "16mm film grain, 3D translucent glass, stipple risograph shading, caustics." |
| **Over-Prescriptive Physics:** Explaining every bone movement, collision angle, or water splash velocity. | **Trusting the World Model:** Describing the scene's emotional context and letting Omni reason the physical interactions. |
| **Full Prompt Rewriting:** Pasting a 400-word prompt again just to change a minor background object. | **Conversational Delta:** "Keep everything identical. Change the background mountains to a futuristic cityscape." |
| **Ignoring the Access Token (`at=`):** Forgetting browser credentials, causing fallback to raw Flash mode. | **Token Factory Lifecycle:** Running `gemcli chrome start` before launching video prompts. |
| **Negative Prompts:** "Do not show cars, do not make it shaky." | **Positive Framing:** "Empty street with zero traffic, locked-off tripod cinematic shot." |

---

## 12. CLI & MCP Quick Reference

### CLI Commands

```bash
# Generate a cinematic video from a text prompt
gemcli video "A futuristic vehicle gliding over a crystal clear lake, cinematic oner" -o flight.mp4

# Vertical video for Shorts/Reels/TikTok
gemcli video "A paper boat on a stream, golden hour" -O portrait -o vertical.mp4

# Higher-quality engine (Pro) in landscape
gemcli video "A luxury watch rotating on black velvet, studio macro" -m pro -O landscape -o watch.mp4

# Create-videos template (style preset) with a custom prompt
gemcli video -T "Logo reveal" "NAIDA'S hair salon" -o logo.mp4
gemcli video -T "Anime" "A cat samurai walking through a bamboo forest" -o anime.mp4

# Reference input: animate a still image (renders 5-15 minutes; match the
# image's orientation). Repeat -f to stack multiple references.
gemcli video "Animate this image: the lantern drifts upward as the stars twinkle. Keep the composition and look." -f lantern.png -O portrait -o lantern.mp4

# Check active usage limits and video quotas
gemcli limits

# Ensure Chrome background daemon is active for Token Factory BotGuard generation
gemcli chrome status
gemcli chrome start
```

### Orientation, Model, and Templates

| Setting | CLI | MCP | Values |
|---------|-----|-----|--------|
| Orientation | `-O` / `--orientation` | `orientation` | `landscape` (16:9, default), `portrait` (9:16) |
| Model | `-m` / `--model` | `model` | `flash` (default), `pro`, `lite`, `thinking` |
| Template | `-T` / `--template` | `template` | Any Create-videos card name, e.g. `Anime`, `Logo reveal`, `8-bit adventure`, `Storybook`, `Product showcase` |
| Reference files | `-f` / `--file` | `files` | Local image/video paths to upload as references (repeatable), e.g. animate a still image |

Known Create-videos templates: Tiny world, Anime, 8-bit adventure, Logo reveal,
Walkthrough, Product showcase, Plush world, Talking pets, Storybook, Birthday
balloons, Pop-up card, Party invite, Origami, Pixelate, Edible city, Chaotic
vlog, Video game, Anniversary, Career day, Cut paper, 80's music video, Moon,
Analyze me, Indie pastel, Science concept, 360 photo booth, Doodle effects,
Comic book, Decades fashion, Step into history, Montage.

The Token Factory drives Gemini's own aspect-ratio, template, and mode-picker
controls in Chrome before capturing the BotGuard-signed request, so the signed
body carries the requested orientation (`inner[55]`, `inner[0][9]`), template
(`inner[0][9]`), and video model (`inner[79]`, `inner[80]`). Downloaded metadata
reports resolution, duration, and orientation. If a template is unavailable the
generation continues as a regular prompt video with a logged warning.

### MCP Tool Usage

For agent workflows, consume the `chat` or `video` tools in a multi-turn process to perform iterative video editing:

```python
# Turn 1: Generate initial base clip
r1 = mcp__gemini-web-mcp__chat(
    action="send",
    prompt="Generate a video of a golden Retriever running on a beach, cinematic low angle."
)

# Turn 2: Edit the character (keep everything else identical)
r2 = mcp__gemini-web-mcp__chat(
    action="send",
    prompt="Change the golden Retriever to a white poodle. Keep the beach environment and camera tracking completely identical.",
    conversation_id=r1["conversation_id"]
)
```
