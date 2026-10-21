# Nano Banana — Image Prompting Guide

Reference guide for generating images via `gemcli` using Nano Banana 2 (Gemini 3.1 Flash Image, default) and Nano Banana Pro (Gemini 3 Pro Image). Distilled from Google's [Ultimate Prompting Guide](https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-nano-banana), [Vertex AI Imagen prompt guide](https://cloud.google.com/vertex-ai/generative-ai/docs/image/img-gen-prompt-guide), [Gemini API Imagen docs](https://ai.google.dev/gemini-api/docs/imagen), and production testing.

**Hard limits:** Prompts must be in **English**. Maximum **480 tokens** per prompt. Text rendered inside images: **25 characters or fewer**, **2–3 phrases maximum**.

## Model Overview

| Model | CLI Flag | Notes |
|-------|----------|-------|
| Nano Banana 2 | `-m flash` | Default. Fast, Pro-quality output. Resolutions: 512px–4K. Wider aspect ratio support. |
| Nano Banana Pro | `-m pro` (default) | Highest quality. Resolutions: 1K–4K. Requires Token Factory. |

Both models embed **C2PA Content Credentials** and a **SynthID watermark** on all generated images.

## Prompt Structure

Every strong prompt follows this structure:

```
[Subject] + [Action] + [Location/Context] + [Composition] + [Style]
```

### Template

```
Subject:
[who or what is the focal point — be specific about appearance, materials, colors]

Action/Pose:
[what is happening — "standing," "exploding outward," "lit from below"]

Location/Context:
[environment, backdrop, time of day, season]

Composition:
[shot type, angle, framing — "medium-full shot, center-framed," "low angle," "aerial view"]

Style:
[camera/film/rendering style — "shot on medium-format analog film," "fashion editorial," "3D render"]

Constraints:
[what to prevent — "no watermark," "no extra text," "no extra limbs"]
```

The **Constraints** slot is where most weak prompts fail. If you don't bound the output, the model gets creative in directions you didn't ask for.

### Quick Template (Single Prompt)

```
A [subject with specific details] [action/pose], [location/context]. [Shot type and angle]. [Camera/film style, lighting, color grading]. [Constraints if needed].
```

## Core Rules

### 1. Be specific — visual facts over vague praise

**Avoid:** stunning, incredible, epic, masterpiece, ultra-detailed, 8K, insanely detailed, breathtaking.

**Prefer:** concrete visual descriptors that actually render:
- "overcast coastal daylight" not "beautiful lighting"
- "worn navy blue tweed jacket" not "nice jacket"
- "ornate elven plate armor, etched with silver leaf patterns" not "cool armor"
- "shallow depth of field, f/1.8" not "bokeh background"
- "slightly worn canvas texture" not "realistic"

Excitement does not render. Concrete visual details do.

### 2. Start with a strong verb for edits

Tell Nano Banana the primary operation first:
- Generate, Create, Render, Transform, Place, Remove, Replace, Redesign

### 3. Use positive framing — describe what you WANT

- ✅ "empty street, no pedestrians" — describe the desired state
- ❌ "no cars" — negative framing is less reliable

### 4. Control the camera

Use photographic and cinematic terms to control perspective, depth, and feel:

**Shot types:** close-up, medium shot, medium-full shot, full body shot, aerial view, bird's-eye view, worm's-eye view, over-the-shoulder shot

**Lens/depth:** shallow depth of field (f/1.8), wide-angle lens, macro lens, low-angle shot, tilt-shift

**Film/camera:** shot on medium-format analog film, GoPro immersive angle, Fujifilm color science, disposable camera flash aesthetic, 35mm film grain

### 5. Text in images — use quotes + specify font

Enclose the desired words in **"quotes"** and name a font:

```
The label reads "LUMIÈRE SERUM" in thin white serif, perfectly legible. No other text.
```

Font options: `bold sans-serif`, `flowing Brush Script`, `heavy blocky Impact`, `thin minimalist Century Gothic`, `elegant italic Garamond`

**Hard limits for in-image text:**
- **25 characters or fewer** per phrase for reliable rendering
- **2–3 phrases maximum** per image
- Generate text concepts conversationally first if unsure, then ask for the image
- Nano Banana supports multi-language output — specify target language: "translate the labels into Korean"
- Use "verbatim" to reinforce exact text reproduction
- Iterate: text placement and font styling vary across generations

### 6. Lighting design — be explicit

Don't say "good lighting." Describe the setup:

| Effect | Prompt |
|--------|--------|
| Product/even | "three-point softbox setup" |
| Dramatic | "chiaroscuro lighting, harsh high contrast, single-source key light" |
| Warm/golden | "golden hour backlighting, long shadows" |
| Moody/cool | "blue hour, diffused ambient light" |
| Cinematic | "cinematic color grading, muted teal tones, high contrast" |
| Natural | "overcast daylight, soft diffused bounce light" |
| Radiant/beauty | "soft radiant studio lighting" |

### 7. Color grading and film stock

Sets the emotional tone:
- "pronounced grain, high saturation, cinematic lighting" — fashion editorial
- "1980s color film, slightly grainy" — nostalgic
- "muted teal tones, cinematic color grading" — modern/moody
- "vibrant, rich textures, high saturation" — bold/commercial

### 8. Multimodal — use reference images

Nano Banana accepts up to **14 reference images** per prompt. Use them for:

**Style transfer:**
```
Recreate this photo in the style of Van Gogh's impasto brushwork.
```

**Structure + texture from separate refs:**
```
Using the attached napkin sketch as the structure and the attached fabric sample as the texture, transform this into a high-fidelity 3D armchair render. Place it in a sun-drenched minimalist living room.
```

**Editing (semantic masking/inpainting):**
```
Remove the man from the photo. Fill the area naturally with the surrounding background.
```
Be explicit about what to **keep exactly the same**.

**Composition editing:**
```
Replace ONLY the white chairs with natural oak wooden chairs. Preserve the camera angle, room lighting, floor shadows, and all surrounding objects.
```

### 9. Iterate — refine conversationally

Nano Banana is conversational. Start with a clean base and refine one change at a time:

```
gemcli chat  # Enter REPL
> Generate a product shot of a skincare serum on black marble
> Now add warm directional lighting from the upper right
> Make the label text read "ÉCLAT" in thin white serif
> Remove the reflection, keep everything else
```

Or use MCP for multi-turn:
```python
r1 = mcp__gemini-web-mcp__chat(action="send", prompt="Generate a fashion model on red backdrop")
r2 = mcp__gemini-web-mcp__chat(action="send", prompt="Change the dress to emerald green", conversation_id=r1["conversation_id"])
```

## Prompt Recipes by Category

### Photorealistic Photography

```
Photorealistic candid photograph of an elderly sailor on a weathered fishing boat. 
Deep facial wrinkles, calloused hands gripping rope, salt-stained wool sweater. 
35mm film, 50mm lens, f/2.8, soft coastal overcast daylight. 
Shallow depth of field, boat rigging blurred in background. 
No retouching, no watermark.
```

### Fashion/Editorial

```
A striking fashion model wearing a tailored brown dress, sleek leather boots, 
and holding a structured handbag. Posing with a confident, statuesque stance, 
slightly turned to the right. Seamless deep cherry red studio backdrop. 
Medium-full shot, center-framed. Fashion magazine style editorial, shot on 
medium-format analog film, pronounced grain, high saturation, cinematic lighting effect.
```

### Product Photography

```
Editorial product shot of a skincare serum in a minimalist amber glass bottle 
on polished black marble. Hard directional light from upper-right creating 
a sharp reflection. Label reads "ÉCLAT SERUM" in thin white serif, perfectly legible. 
Deep charcoal background. No props, no hands, no watermark.
```

### Beauty Shot with Text

```
High-end glossy commercial beauty shot of a sleek nude-colored face moisturizer jar 
on a warm studio background. Soft radiant lighting. Three lines of text beside the jar:
"GLOW" in a flowing elegant Brush Script font (top),
"10% OFF" in heavy blocky Impact font (middle),
"Your First Order" in thin minimalist Century Gothic font (bottom).
No other text. No watermark.
```

### Typographic Design

```
Typographic poster, solid black background. Bold letters spell "New York" filling 
the center of the frame. The text acts as a cut-out window — a photograph of the 
New York City skyline is visible ONLY inside the letterforms. Clean edges, 
no drop shadow, no additional elements.
```

### 3D Product Render

```
High-fidelity 3D render of a minimalist armchair with a walnut wood frame and 
cream boucle upholstery. Placed in a sun-drenched minimalist living room, 
white plaster walls, concrete floor. Soft diffused afternoon light from left. 
Photorealistic materials, subtle ambient occlusion, no harsh shadows.
```

### Furniture/Interior

```
Scandinavian-style living room interior, late afternoon golden hour light from 
floor-to-ceiling windows. Pale oak flooring, linen sofa in warm ecru, terracotta 
ceramic vase with dried pampas grass. Architectural photography feel, 
wide-angle lens, slight tilt-shift. No people. No watermark.
```

### Real-Time / Live Data

```
[Search for current weather and time in Tokyo right now]
Visualize this as a miniature city-in-a-cup concept: a tiny Tokyo skyline inside 
a ceramic coffee mug, weather conditions reflected in the scene (rain, snow, sunshine). 
Realistic lighting matching the actual time of day. Macro lens, shallow depth of field.
```

### Cinematic Scene

```
Cinematic still from a noir thriller. Rain-slicked cobblestone alley, 1940s Paris. 
A lone detective in a trench coat stands under a dim gas lamp, back to camera. 
Mist, low fog. Single-source overhead key light creating harsh shadows. 
35mm film, slightly underexposed. Deep shadows, film grain. No text.
```

### Infographic / Diagram

```
Clean flat-design infographic explaining the water cycle. 
Four labeled stages: Evaporation → Condensation → Precipitation → Collection. 
Soft blue and green color palette, white background. 
Icon-based illustration style, thin strokes. Text labels in bold sans-serif. 
No gradients, no shadows. Suitable for a science textbook.
```

### Ad / Marketing

```
Billboard advertisement for an outdoor hiking boot brand. 
Rocky mountain summit at golden hour, lone hiker in foreground wearing the boots. 
Bold headline: "BUILT FOR THIS" in heavy white sans-serif, upper left. 
Tagline: "Summit Series 2026" in thin white below. 
Cinematic wide-angle, high contrast, dramatic sky. No logo, no extra text.
```

## Common Mistakes

| Mistake | Instead |
|---------|---------|
| "Amazing lighting" | "Three-point softbox, soft bounce light from the left" |
| "Ultra-realistic" | "Photorealistic, 35mm film, shallow depth of field" |
| "8K masterpiece" | Specific visual details about materials, surfaces, light |
| Text without quotes | Put desired text in "quotes" and name a font |
| "No cars" (negative) | "Empty street, no traffic" (positive) |
| Long run-on paragraph | Structured sections: Subject, Composition, Style, Constraints |
| No constraints | Always add: "No watermark. No extra limbs. No extra text." |

## Art Styles & Rendering Modes

Use these to lock in the visual language of the output. Combine freely.

**Photography:**
```
photorealistic, studio photo, HDR, 4K, 35mm film, polaroid, film noir, black and white
```

**Painting:**
```
oil painting, watercolor, pastel painting, impressionism, renaissance, pop art
```

**Drawing/Illustration:**
```
technical pencil drawing, charcoal drawing, digital art, 3D cartoon style, flat vector
```

**Specialty:**
```
neon sign style, mosaic style, glowing style, made of glass, made of metal,
in the shape of a butterfly, tilt-shift miniature, macro photograph
```

**Reference-image style transfer (multimodal):**
Mark references with brackets when using multiple images:
```
Generate an image in neon sign style [1] based on the following caption: "Tokyo at 3am"
```

## Quality Modifiers That Actually Work

Per Google's official Imagen 3 docs, these descriptors reliably affect output quality:

| Modifier | Effect |
|----------|--------|
| `photorealistic` | Enables high-fidelity photo rendering mode |
| `high-quality` | General quality boost |
| `4K` / `HDR` | Upscaled resolution and dynamic range |
| `studio photo` | Professional lighting/sharpness |
| `by a professional` | Elevates illustration/art quality |
| `detailed` | More intricate rendering |
| `sharp` / `vibrant colors` | Clarity and saturation |

**Avoid:** stunning, epic, masterpiece, incredible, ultra-detailed, 8K, insanely detailed — these don't render; concrete visual details do.

## CLI Quick Reference

```bash
# Generate (Nano Banana Pro by default)
gemcli image "A product shot of a leather wallet on marble" -o wallet.png

# Generate with Nano Banana 2 (Flash, faster)
gemcli image "A futuristic city at night" -m flash -o city.png

# Conversational editing — enter REPL, use Gemini chat
gemcli chat -m pro   # Then iterate image prompts conversationally

# Check quota before generating
gemcli limits        # Verify image quota available

# Chrome must be running for image generation
gemcli chrome status
gemcli chrome start  # If not running
```

## MCP Quick Reference

```python
# Generate and save
mcp__gemini-web-mcp__image(action="generate", prompt="...", output_path="img.png")

# Generate without saving (returns URL)
mcp__gemini-web-mcp__image(action="generate", prompt="...")

# Download from URL
mcp__gemini-web-mcp__image(action="download", image_url="https://...", output_path="img.png")

# Check limits before generating
mcp__gemini-web-mcp__limits()
```

## Aspect Ratios

| Ratio | Use case |
|-------|---------|
| `1:1` | Square — social, avatars |
| `16:9` | Landscape — video thumbnails, banners |
| `9:16` | Portrait — mobile, stories |
| `3:4` | Classic portrait |
| `4:3` | Classic landscape |

The Gemini Images composer exposes a five-option aspect-ratio control; gemcli
drives it directly so the request carries the exact ratio:

```bash
gemcli image "A vertical movie poster" -A 9:16 -o poster.png
gemcli image "A wide banner" -A 16:9 -m flash -o banner.png
gemcli image "A square avatar" -A 1:1
```

MCP: `mcp__gemini-web-mcp__image(action="generate", prompt="...", aspect="9:16")`

Aliases are accepted: `square` → 1:1, `portrait`/`vertical` → 9:16,
`landscape`/`horizontal`/`wide` → 16:9.

Model note: the prompt-based path still matters — aspect support is a UI
setting, while other ratios (3:2, 2:3, 4:5, 5:4, 21:9, 4:1, 1:4, 1:8, 8:1)
must be requested in the prompt text if the model supports them.
