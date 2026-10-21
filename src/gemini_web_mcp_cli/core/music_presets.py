"""Music style presets for Lyria 3.5 (Gemini's music generation).

Each preset contains a unique ID, display name, reference assets, and a detailed
system prompt that guides Lyria 3.5's output style. These presets mirror the 16
"Pick a track to remix" options in the Gemini web UI.

The preset data is injected into the StreamGenerate request at inner[0][9][6].
"""

from __future__ import annotations

# fmt: off
MUSIC_PRESETS: dict[str, dict] = {
    "90s-rap": {
        "id": "7SAXCf75CToiwWi",
        "name": "90's rap",
        "image_url": "https://www.gstatic.com/bard-robin-zs/musicgen/image_assets/webp/boom_bap_v2.webp",
        "audio_url": "https://www.gstatic.com/bard-robin-zs/musicgen/audio_assets/30s/90_s_rap.mp3",
        "system_prompt": (
            "90's Rap\n\nFollow the user prompt below to guide the creation of the rap.\n\n"
            "If (and only if) the user prompt is blank, the rap should be about knowledge of "
            "self and striving for success.\n\nUse metaphor, clever wordplay and occasional "
            "internal rhymes.\n\nUse these vocalist parameters to describe the voices in the "
            "captions, but DO NOT use elements of this description as part of the lyrics.\n"
            "Vocalist Parameters:\n[Lineage]: 90s East Coast Boom Bap / Golden Age Hip Hop\n"
            "[Energy level]: High, confident\n[Sociolect/Locale/accent]: NorthAm-NYC "
            "(Brooklyn/Queens), 1990s Urban AAVE\n[Lexicon]: Street Vernacular (90s era "
            'specific: "ill," "word up," "peace," "cipher"), intricate rhyme schemes, '
            "storytelling\n[Vocal Avatar]: Male Rapper. Projection: High/Declamatory. Texture: "
            "Gritty, raw, punchy, aggressive delivery.\n[VOCAL EFFECTS]: Heavy compression, "
            "manual doubling on end rhymes, slight tape saturation, ad-lib backings. No "
            "autotune.\n[Instrumentation and Development]: Dusty sampled breakbeats (heavy kick, "
            "snapping snare), filtered jazz bassline, chopped soul piano or horn samples, "
            "turntable scratching.\n\nStart in a fully developed verse (mid song) and focus on "
            "the build up to the chorus to feature the most fully developed, interesting and "
            "exciting part of the song.\n\nUser Prompt:\n"
        ),
    },
    "latin-pop": {
        "id": "7GRty74JGzGRHRA",
        "name": "Latin pop",
        "image_url": "https://www.gstatic.com/bard-robin-zs/musicgen/image_assets/webp/latin_pop_v2.webp",
        "audio_url": "https://www.gstatic.com/bard-robin-zs/musicgen/audio_assets/30s/latin_pop.mp3",
        "system_prompt": (
            "Create a Modern Latin Pop track\n\nFollow the user prompt below to guide the "
            "creation of the song.\n\nVocalist Parameters:\n[Lineage]: Modern Latin Pop / "
            "Alt-Reggaeton / Global Pop\n[Energy level]: Medium-High (Sophisticated, "
            "Groove-oriented)\n[Sociolect/Locale/accent]: Miami/San Juan Spanglish (Seamless "
            "Code-Switching)\n[Lexicon]: Contemporary Urban, Emotional, Hedonistic, "
            "Conversational\n[Vocal Avatar]: Melodic Rapper/Singer, Low Projection "
            "(Intimate/Close-Mic), Texture: Breathy, Whisper-Pop, Sultry, Smooth\n"
            '[VOCAL EFFECTS]: Visible "Metallic" Auto-Tune (Stylistic), Dry Mix (High '
            "Presence), Compression, Minimal Reverb, Saturation\n[Instrumentation and "
            "Development]: Digital-organic hybrid; soft dembow skeleton (snaps, shakers, "
            "g\u00fciro), deep trap 808 bass, strummed nylon-string guitar, plucked charango, "
            "underwater synth pads, bright 80s digital leads. Intro with ambient city "
            "sounds/birds and vocal runs, building dynamically to a bass-heavy chorus.\n\n"
            "Start in a fully developed verse (mid song) and focus on the build up to the "
            "chorus to feature the most fully developed, interesting and exciting part of the "
            "song.\n\nUser Prompt:"
        ),
    },
    "folk-ballad": {
        "id": "AwRCEdJqEyXWXbB",
        "name": "Folk ballad",
        "image_url": "https://www.gstatic.com/bard-robin-zs/musicgen/image_assets/webp/folk_ballad_v2.webp",
        "audio_url": "https://www.gstatic.com/bard-robin-zs/musicgen/audio_assets/30s/folk_ballad.mp3",
        "system_prompt": (
            "A tender modern folk ballad at a steady 80 BPM. The vocals are a delicate female "
            "performance\u2014breathy, raw, and infused with a sense of healing. The song has a "
            "theme of embracing one's flaws.  It's a track designed to feel like sitting in the "
            "light, finally being kind to yourself.'\n\nFollow the user prompt to further shape "
            "the track\n\nVocalist Parameters:\n[Lineage]: Contemporary Indie Folk / Acoustic "
            "Singer-Songwriter\n[Energy level]: Low\n[Sociolect/Locale/accent]: NorthAm-Indie "
            "Soft (Neutral/Intimate)\n[Lexicon]: Intimate, Vulnerable, Reflective, Emotional\n"
            "[Vocal Avatar]: Female Singer, Low Projection (Close-mic), Breathy, Airy, Raw, "
            'Warm tone\n[VOCAL EFFECTS]: Upfront and intimate mix, beautiful reverb for '
            '"sun-soaked" space, minimal compression to keep dynamics raw, no layering or '
            "backing vocals.\n[Instrumentation and Development]: Solo acoustic guitar (mahogany "
            "tone, soft fingerstyle patterns), steady 80 BPM, zero percussion or synth pads. "
            "Development relies on the dynamic intensity of the guitar picking (moving from "
            "sparse plucks to fuller arpeggios) and the rising emotional arc of the melody.\n\n"
            "Start in a fully developed verse (mid song) and focus on the build up to the "
            "chorus to feature the most fully developed, interesting and exciting part of the "
            "song.\n\nUser Prompt:"
        ),
    },
    "8-bit": {
        "id": "5YcQ7ninNzGzST8",
        "name": "8-bit",
        "image_url": "https://www.gstatic.com/bard-robin-zs/musicgen/image_assets/webp/8_bit_gaming_v2.webp",
        "audio_url": "https://www.gstatic.com/bard-robin-zs/musicgen/audio_assets/30s/8_bit.mp3",
        "system_prompt": (
            "Make 8-bit chiptune music:\nAct as a master chiptune composer working within the "
            "strict limitations of 8-bit hardware (two pulse wave channels, one triangle wave "
            "channel, and one noise channel). Your primary goal is 'functional melodicism' "
            "driven by the 'Earworm' philosophy. Construct a catchy, high-energy lead melody on "
            "the primary pulse channel using strong, hummable intervals and call-and-response "
            "phrasing. Since you cannot rely on high-fidelity atmosphere, utilize syncopated "
            "rhythms and rapid arpeggios to simulate complex chords and prevent the loop from "
            "feeling static. The melody must be distinct enough to be whistled after one listen, "
            'cutting clearly through the mix."\n\n8-Bit "Instrumentation" and Palette\n"Adapt '
            "the user's level description into specific waveform manipulations to define the "
            "aesthetic. For playful or kinetic platforming descriptions, use short, staccato "
            "square waves with swing rhythms to emulate a Ragtime or Jazz feel. For "
            "high-adventure or fantasy settings, utilize sustained pulse waves with vibrato and "
            "smooth envelope attacks to mimic woodwinds or strings. For sci-fi or isolationist "
            "levels, focus on the noise channel for industrial percussion and use dissonant "
            "pitch bends or echo-like volume envelopes. Define the emotional tone purely through "
            'duty-cycle changes, pitch bends, and volume envelopes."\n\nStructural Loops and '
            'Channel Management\n"Structure the composition as a seamless, infinite loop '
            "designed for gameplay. Compose with a solid harmonic foundation where the triangle "
            "wave provides a driving bassline, anchoring the higher-frequency pulse waves. "
            "Design the track to handle 'channel stealing,' ensuring the arrangement remains "
            "identifiable even if one channel is momentarily silenced to play a sound effect "
            "(like a jump or item collection). If the user requests high intensity, increase the "
            "tempo and arpeggio density; for exploration, strip the track back to sparse, "
            "echoing notes, allowing the silence between the waveforms to create a sense of "
            'space."\n\nUser prompt:'
        ),
    },
    "workout": {
        "id": "48cmHB66Mu2UTWu",
        "name": "Workout",
        "image_url": "https://www.gstatic.com/bard-robin-zs/musicgen/image_assets/webp/workout_v2.webp",
        "audio_url": "https://www.gstatic.com/bard-robin-zs/musicgen/audio_assets/30s/workout.mp3",
        "system_prompt": (
            "A high-octane, instrumental EDM track specifically engineered for peak physical "
            "performance and workout motivation.\n\nIf included, use the user prompt to guide "
            "the creation.\n\nThe foundation must be built on a relentless, driving percussion "
            "section featuring a thunderous, heavy-hitting kick drum tailored to the requested "
            "BPM, locked in with a tight, side-chain compression that creates a powerful "
            '"pumping" rhythm. Layer this with closed hi-hats in 16th-note patterns and a '
            "snapping, punchy snare or clap that cuts through the mix. The groove should be "
            "kinetic and propulsive, utilizing percussive polyrhythms or tribal tom fills to "
            "maintain constant forward momentum, ensuring there are no drops in energy that "
            "would break the listener's focus.\n\n*Instrumentation and Synthesis*\nConstruct the "
            "melodic and harmonic layers using expansive, modern sound design. Utilize massive, "
            "detuned supersaw synthesizer stacks for anthemic chord progressions that evoke a "
            "sense of triumph and endurance. Interlace these with rapid-fire, crystalline plucks "
            "and interlocking arpeggiators that span multiple octaves to add texture and urgency. "
            "The low end must be dominated by a gritty, saturated bassline\u2014switching between "
            "rolling sub-bass or aggressive mid-range growls depending on intensity\u2014that "
            "creates a visceral physical vibration. Employ extensive transitional effects, "
            "including white noise sweeps, pitch-bending risers, and impact booms, to signal "
            "distinct sections (breakdown, buildup, drop) without the use of any vocal chops or "
            'lyrics.\n\n*Production and Style Variable*\nA "festival-main-stage" production '
            "quality with a wide stereo field, crystal-clear high-end frequency, and a tightened "
            "low-end for maximum impact on headphones or gym sound systems.  Regardless of the "
            'sub-genre, ensure the arrangement follows a high-energy "buildup-to-drop" formula '
            "designed to synchronize with high-intensity interval training, maintaining a "
            "euphoric and aggressive atmosphere throughout.\n\nUser prompt:"
        ),
    },
    "reggaeton": {
        "id": "xtzZQGYDaQfivzP",
        "name": "Reggaeton",
        "image_url": "https://www.gstatic.com/bard-robin-zs/musicgen/image_assets/webp/reggaeton.webp",
        "audio_url": "https://www.gstatic.com/bard-robin-zs/musicgen/audio_assets/30s/reggaeton.mp3",
        "system_prompt": (
            "Upbeat Reggaeton\n\nFollow the user prompt below to shape the track.\n\nIf (and "
            'only if) the user prompt is empty, make the song about "El Perreo"\n\nStructure: '
            "Music should be infectiously rhythmic, after a very short intro, start the verse at "
            "2 seconds and start a group chorus at around 12 seconds.\n\nVocalist Parameters:\n"
            "[Lineage]: Modern Reggaeton / Neoperreo\n[Energy level]: High\n"
            "[Sociolect/Locale/accent]: Caribbean Spanish (Puerto Rican dialect) with occasional "
            "Spanglish\n[Lexicon]: Street Vernacular / Party Slang (focus on nightlife, "
            "dancing/perreo, seduction)\n[Vocal Avatar]: Male Rapper/Singer Hybrid (Flow "
            "Mel\u00f3dico); Projection: Confident and rhythmic; Texture: Smooth with slight "
            "nasal quality and sharp articulation\n[VOCAL EFFECTS]: Heavy Autotune (pitch "
            "correction), crisp saturation, stereo widening on ad-libs, heavy compression, short "
            "plate reverb, delay throws on end phrases\n[Instrumentation and Development]: "
            "Driving classic Dembow rhythm (kick-snare pattern), booming sub-bass, bright synth "
            "plucks or tropical mallet sounds, high-energy buildup with risers leading to a "
            "drop.\n\nStart in a fully developed verse (mid song) and focus on the build up to "
            "the chorus to feature the most fully developed, interesting and exciting part of "
            "the song."
        ),
    },
    "rnb-romance": {
        "id": "9ccBNEUfLMWL3tq",
        "name": "R&B romance",
        "image_url": "https://www.gstatic.com/bard-robin-zs/musicgen/image_assets/webp/rnb_romance.webp",
        "audio_url": "https://www.gstatic.com/bard-robin-zs/musicgen/audio_assets/30s/rnb_romance.mp3",
        "system_prompt": (
            "Create a comical romantic R&B slow jam\n\nStrictly follow the user prompt below:\n\n"
            "If (and only if) the user prompt is empty, the song should be about a sock finding "
            "their match, emotional 90s style, soulful ad-libs, dryer heat.\n\nVocalist "
            "Parameters:\n[Lineage]: 90s Contemporary R&B / New Jack Swing Ballad\n[Energy "
            "level]: Medium-Low (Sensual but intensely emotional)\n[Sociolect/Locale/accent]: "
            "NorthAm-Standard Black English / Southern Soul influence\n[Lexicon]: Romantic "
            "Hyperbole, Laundry-based metaphors (lint, static cling, tumble dry), Street "
            "Vernacular, Soulful Slang\n[Vocal Avatar]: Male R&B Crooner, Tenor to falsetto "
            "range, chest-voice belting in the bridge, texture is smooth with occasional "
            '"churchy" grit and heavy vibrato.\n[VOCAL EFFECTS]: Lush 90s plate reverb, heavy '
            "vocal doubling on the chorus, intricate three-part harmonies, prominent ad-libs "
            'panned left and right, crystal clear "expensive" mix level.\n[Instrumentation and '
            'Development]: Slow-tempo 808 drum machine with "wet" snares, a deep synth bassline, '
            "shimmering electric piano (Rhodes), and a dramatic saxophone solo. The song builds "
            "from a sparse, steamy verse into a grand, harmonically dense climax with rapid-fire "
            "soulful runs.\nStart in a fully developed verse (mid song) and focus on the build "
            "up to the chorus to feature the most fully developed, interesting and exciting part "
            "of the song.\n\nUser Prompt:"
        ),
    },
    "kawaii-metal": {
        "id": "B8Ex4U4GdEoD2oR",
        "name": "Kawaii metal",
        "image_url": "https://www.gstatic.com/bard-robin-zs/musicgen/image_assets/webp/kawaii_metal_v2.webp",
        "audio_url": "https://www.gstatic.com/bard-robin-zs/musicgen/audio_assets/30s/kawaii_metal.mp3",
        "system_prompt": (
            "'Kawaii Metal' (in Japanese unless otherwise specified)\n\nFollow the user prompt "
            "to shape the track.\n\nBe sure that the aggressive male death metal voice comes in "
            "after the first few lines and does a call and response with the female vocals. make "
            "that voice very growly, distorted, and a little scary.\n\nVocalist Parameters:\n"
            "[Lineage]: Kawaii Metal (J-Pop / Metalcore Fusion)\n[Energy level]: Very High / "
            "Hyperactive\n[Sociolect/Locale/accent]: Japanese (Standard Tokyo) with high-energy "
            "Idol intonation\n[Lexicon]: Cute/Kawaii aesthetic, catchy hooks, simple positive "
            "themes juxtaposed with chaotic imagery, occasional English loanwords\n"
            "[Vocal Avatar]: Female ; high-pitched, nasal, bright, and enthusiastic "
            '"anime" timbre; contrasted by aggressive death metal style screaming/growling '
            "backing vocals (interjections)\n[VOCAL EFFECTS]: Heavily polished modern pop "
            "production; tight pitch correction; crisp EQ; synchronized double-tracking on "
            "choruses; subtle delay throws; mix level prominent and forward\n[Instrumentation "
            "and Development]: Aggressive downtuned distorted guitars and rapid-fire double-bass "
            "drumming (blast beats) playing upbeat major-key J-Pop chord progressions; manic "
            "synthesizer arpeggios; heavy breakdowns transitioning abruptly into sugary pop "
            "melodies\n\nStart in a fully developed verse (mid song) and focus on the build up "
            "to the chorus to feature the most fully developed, interesting and exciting part of "
            "the song.\n\nUser Prompt:"
        ),
    },
    "cinematic": {
        "id": "eZcEiADTSQPTw48",
        "name": "Cinematic",
        "image_url": "https://www.gstatic.com/bard-robin-zs/musicgen/image_assets/webp/cinematic_score_v2.webp",
        "audio_url": "https://www.gstatic.com/bard-robin-zs/musicgen/audio_assets/30s/cinematic.mp3",
        "system_prompt": (
            "Generate a grand, instrumental, cinematic orchestral score for the film moment "
            "described by the user prompt below. if none is specified, create the music for an "
            "epic chase scene across fields and deserts.\n\nDrive the composition with a rhythmic "
            "foundation that combines motoric energy with sophisticated phrasing. Use driving "
            "string ostinatos in the low register to provide forward momentum, allowing the "
            "brass melodies to soar above without the music becoming stagnant. Construct the "
            "main themes using a developmental structure where a short musical idea is "
            "introduced, repeated, and then expanded into a longer, complex concluding phrase. "
            "Incorporate subtle syncopation and offset accents to give the track a propulsive, "
            "kinetic quality distinct from standard marches.\n\nUser Prompt:\n"
        ),
    },
    "emo": {
        "id": "35PvCx4QmjYKs3i",
        "name": "Emo",
        "image_url": "https://www.gstatic.com/bard-robin-zs/musicgen/image_assets/webp/emo_v2.webp",
        "audio_url": "https://www.gstatic.com/bard-robin-zs/musicgen/audio_assets/30s/emo.mp3",
        "system_prompt": (
            "Midwest Emo\n(Subgenres: Math Rock, Post-Hardcore, Indie Rock)\n\nFollow the user "
            "prompt to shape the track.\n\nVocalist Parameters:\n[Lineage]: Midwest Emo, Math "
            "Rock, Post-Hardcore, Indie Rock\n[Energy level]: High Dynamic Range (oscillating "
            "between anxious restraint and explosive catharsis)\n[Sociolect/Locale/accent]: "
            'US-Midwest / Suburban General American (slightly nasal, distinctive "indie" '
            "affectation)\n[Lexicon]: Confessional, introspective, conversational, suburban "
            "vernacular, hyper-specific nostalgia\n[Vocal Avatar]: Male Singer. mid register in "
            "verses to upper register in choruses.  Sounds a little pathetic.  Style: Shifts "
            "rapidly between spoken-word mumbling, melodic whining, and strained, emotive "
            "shouting/yelping. Texture: Raw, unpolished, prone to voice cracks for emotional "
            "effect.\n[VOCAL EFFECTS]: Dry to minimal room reverb, heavy compression to catch "
            "dynamic spikes, occasional gang vocals (shouted unison) for emphasis, strictly no "
            "autotune.\n[Instrumentation and Development]: Twinkly clean electric guitars "
            "(Telecasters in open tunings like DAEAC#E) utilizing complex two-handed tapping and "
            "angular riffs.  driving melodic basslines, and busy, syncopated drumming. Builds "
            "from intricate noodling to a wall-of-sound distortion climax.\n\nStart in a fully "
            "developed verse (mid song) and focus on the build up to the chorus to feature the "
            "most fully developed, interesting and exciting part of the song.\n\nUser Prompt:"
        ),
    },
    "afropop": {
        "id": "A6PiNVTzfyqf2WC",
        "name": "Afropop",
        "image_url": "https://www.gstatic.com/bard-robin-zs/musicgen/image_assets/webp/afro_pop_v2.webp",
        "audio_url": "https://www.gstatic.com/bard-robin-zs/musicgen/audio_assets/30s/afropop.mp3",
        "system_prompt": (
            "Afrobeats\n\nFollow the user prompt to shape the track:\n\nIf (and only if) the "
            'user prompt is empty, make the song about "breakfast" (heartbreak)\n\nStructure: '
            "Music should be infectiously rhythmic and mysterious, start a group chorus at around "
            "10 seconds.\n\nVocalist Parameters:\n[Lineage]: Melodic Afro-Pop / Contemporary "
            'Highlife Fusion\n[Energy level]: Mid-Tempo "Bop" (Relaxed intensity, infectious '
            "groove)\n[Sociolect/Locale/accent]: Urban Lagosian / Nigerian Pidgin\n[Lexicon]: "
            '"Naija" Pop Vernacular (Nigerian Pidgin English, Yoruba loanwords, emotive '
            'vocalizations like "Odo," "Yeh yeh," "Joor"),\n[Vocal Avatar]: The "Crooner" '
            "(Melody-centric); High Tenor or Falsetto-capable, agile melismatic runs, sweet and "
            'airy tone with strong "Lamba" (rhythmic phrasing)\n[VOCAL EFFECTS]: Prominent '
            'stylistic Auto-Tune (hard-tuned for effect), "Airy" high-shelf EQ boost, '
            "wideners/doublers on the chorus, lush distinctive reverb tail\n[Instrumentation and "
            'Development]: Syncopated rimshots, complex shaker layers, muted "palm-wine" guitar '
            "riffs, melodic Log Drum bass (Amapiano hybrid), warm rhodes chords; driving but "
            "uncluttered polyrhythm\n\nUser Prompt:"
        ),
    },
    "forest-bath": {
        "id": "AtyAtQ8jwjm5GKb",
        "name": "Forest bath",
        "image_url": "https://www.gstatic.com/bard-robin-zs/musicgen/image_assets/webp/forest_bath_v3.webp",
        "audio_url": "https://www.gstatic.com/bard-robin-zs/musicgen/audio_assets/30s/forest_bath.mp3",
        "system_prompt": (
            "A generative ambient soundscape characterized by an immediate, simultaneous blend "
            "of repeating melodic loops of varying lengths and high-fidelity natural field "
            "recordings of a lush forest and a constant, gentle flowing stream. These sounds "
            "begin fully bloomed at second zero to create a constantly evolving, non-linear "
            "texture designed to induce a state of calm and environmental transparency.\n\nThe "
            "composition features inherently low-pass filtered, warm, minimalist analog "
            "synthesizer pads with long attack and decay times (starting at peak volume), "
            "interspersed with sparse, ethereal electric piano notes that feel suspended in "
            "space. The harmony is static and airy, utilizing Major 7th and Add9 chords "
            "processed through massive hall reverb and subtle vintage tape-loop effects.\nThe "
            'frequency profile is "dark" and non-fatiguing with a consistent dynamic range and '
            "absolutely no drums, percussion, beats, or rhythmic elements."
        ),
    },
    "k-pop": {
        "id": "4xsPHm5U3apV59Z",
        "name": "K-pop",
        "image_url": "https://www.gstatic.com/bard-robin-zs/musicgen/image_assets/webp/k_pop_v2.webp",
        "audio_url": "https://www.gstatic.com/bard-robin-zs/musicgen/audio_assets/30s/k_pop_v3.mp3",
        "system_prompt": (
            "Modern K-Pop (65% Korean lyrics)\n\nFollow the user prompt below:\n\nIf (and only "
            "if) the user prompt is empty, make the song about self-love and empowerment.\n\n"
            "Structure: The music should be energetic and modern throughout.  Start the track in "
            "a fully developed verse and focus on a rapid dramatic build up to a group chorus at "
            "the 10 second mark.\n\nVocalist Parameters:\n[Lineage]: Modern K-Pop\n[Energy "
            "level]: High\n[Sociolect/Locale/accent]: Standard Seoul Korean mixed with Global "
            "English hooks\n[Lexicon]: Trendy, confident, youthful slang, emotive declarations\n"
            "[Vocal Avatar]: Group Dynamic (randomize gender); Voice 1: confident, melodic "
            "rapper in Korean; Voice 2: Silky, soaring high-tenor singers; Polished and punchy\n"
            "[VOCAL EFFECTS]: Heavily produced, crisp EQ, stylish autotune on rap, wide layered "
            "harmonies on pre-chorus, bright reverb\n[Instrumentation and Development]: Pulsing "
            "heavy 808 bass, staccato synth leads, rapid-fire hi-hats, building tension with "
            "risers into an explosive, anthem-like drop\n\nUser Prompt:"
        ),
    },
    "birthday-roast": {
        "id": "74LvchoZaKQ22jq",
        "name": "Birthday roast",
        "image_url": "https://www.gstatic.com/bard-robin-zs/musicgen/image_assets/webp/country_birthday_roast_v2.webp",
        "audio_url": "https://www.gstatic.com/bard-robin-zs/musicgen/audio_assets/30s/birthday_roast.mp3",
        "system_prompt": (
            "A country song gently roasting someone on their birthday:\n\nStrictly follow the "
            "user prompt below.\n\nIf the user prompt is empty, make it about backhanded "
            "compliments and aging.\n\nVocalist Parameters:\n[Lineage]: Classic Country / 1970s "
            "Outlaw Country\n[Energy level]: Medium\n[Sociolect/Locale/accent]: US Southern "
            "(Texas/Tennessee), Rhotic, distinct twang\n[Lexicon]: Blue-collar storytelling, "
            "conversational, heartache and highway imagery\n[Vocal Avatar]: Male Baritone "
            "Singer. Rich, warm, resonant, slight nasal croon, confident but weary\n"
            "[VOCAL EFFECTS]: Vintage plate reverb, subtle slapback delay, vocals mixed "
            "prominent and dry-to-center, slight tape saturation\n[Instrumentation and "
            "Development]: Acoustic guitar strums, clean electric Telecaster with chicken-pickin'"
            " fills, crying pedal steel swells, walking bassline, shuffled drum beat.\n\n"
            "User Prompt:"
        ),
    },
    "folk-a-cappella": {
        "id": "32oyidk5mmTG8Ro",
        "name": "Folk a cappella",
        "image_url": "https://www.gstatic.com/bard-robin-zs/musicgen/image_assets/webp/traditional_harmonies_v2.webp",
        "audio_url": "https://www.gstatic.com/bard-robin-zs/musicgen/audio_assets/30s/folk_a_cappella.mp3",
        "system_prompt": (
            "A song in the style of gentle soft Appalachian a cappella. Three part harmony, long "
            "held notes with melisma. Beautiful and inspiring. No instruments, just voices. The "
            "voices are untrained and imperfectly textured. (Avoid echoing the lead line with "
            "backup voices, any kind of vocal rhythmic time keeping (like doo-wops)).\n\nFollow "
            "the user prompt below to shape the song. When no user prompt is present, the song "
            "should be about connection to nature, while avoiding any religious imagery or "
            "vocabulary.\n\nVocalist Parameters:\n[Lineage]: Traditional Appalachian Folk, "
            "Vocals only. No instruments.\n[Energy level]: Low to Moderate (Reverent and "
            "swelling)\n[Sociolect/Locale/accent]: Southern Appalachian Mountain Dialect (R-full, "
            "natural twang, vowels slightly flattened)\n[Lexicon]: Pastoral, Archaic/Poetic "
            '(e.g., "valley," "glory," "yonder," "weary")\n[Vocal Avatar]: Three-part Mixed '
            "Ensemble. Untrained, raw, and unpolished texture. Lead voice carries a mid-range, "
            "lonesome quality with nasal resonance. Pitch delivery includes natural sliding "
            "(scooping) and extensive melismatic decoration on long vowels.\n[VOCAL EFFECTS]: "
            "Wooden church reverb. No pitch correction or smoothing. Harmonies are homophonic "
            "(singing the same words simultaneously) rather than call-and-response.\n"
            "[Instrumentation and Development]: Strictly A Cappella. No percussion or rhythmic "
            "vocalizations. The song develops through the slow, swelling dynamics of the three "
            "voices locking into open chords, sustaining long notes with unwavering intensity "
            "before resolving.\nStart in a fully developed verse (mid song) and focus on the "
            "build up to the chorus to feature the most fully developed, interesting and exciting "
            "part of the song.\n\nUser Prompt:"
        ),
    },
    "bad-music": {
        "id": "BNvHQbhDZNpRuYx",
        "name": "Bad music",
        "image_url": "https://www.gstatic.com/bard-robin-zs/musicgen/image_assets/webp/bad_music_v2.webp",
        "audio_url": "https://www.gstatic.com/bard-robin-zs/musicgen/audio_assets/30s/bad_music.mp3",
        "system_prompt": (
            "Make really bad music. Just awful, but really kinda hilarious too. Joyful beautiful "
            "chaos. A track that makes you laugh at how absurd it is. Like why would anyone ever "
            "make this.\nfollow the user prompt to guide the creation of the lyrics in each "
            "section below:\n\nIf (and only if) the user prompt is empty, choose a random, "
            "funny, rare and cute non-mammalian animal and write the entire song from the "
            "perspective of that animal using many unique details about that animal's life. Avoid "
            "any foul language.\n\nNote: These are not lyrics, Strictly avoid creating lyrics "
            "about these structural elements:\n\nStructure (heavy textural shifts in "
            "instrumentation) follow this timecode exactly:\n\n0.0s: Instrumental IDM music "
            "enters aggressively\n\n3.0s: Loudly stating what animal you are through a "
            "metaphor.\n\n5.0s: A weird spoken word sample from an old vinyl record, scratched "
            "badly by a terrible DJ\n\n10.0s: A terrible tuba and accordion solo.\n\n14.0s: "
            "Enters a cute high pitched animal voice speaking in LOL Cat language (over the "
            "tuba/accordion solo).\n\n17.0s: an absurd digital assistant message sung by very "
            "BAD TTS.\n\n20.0s: Chopped up robot vocals scratched badly on a turntable.\n\n"
            "23.0s: a very quiet whispering folk singer emotional drivel\n\n26.0s: An absolutely "
            "shredding death metal vocals\n\n27.0s: Sign off at the end with a very earnest tone "
            "of voice.\n\nVocalist Parameters:\n[Lineage]: Experimental Glitch-Comedy / "
            "Polka-Dubstep Fusion\n[Energy level]: Manic / Chaotic / Very High Energy\n"
            "[Sociolect/Locale/accent]: Shifting rapidly between Guttural Demonic, Hyper-cute "
            "Internet Slang, Broken Text-to-Speech, and Soft Acoustic Whispers, soaring "
            "harmonies\n[Lexicon]: Biological processes, incoherent philosophy, surrealist banal "
            "observations, sappy emotional drivel.\n[Vocal Avatar]: A chaotic ensemble: An "
            "aggressive death metal growler, a pitch-shifted 'chipmunk' squeaker, a glitching "
            "low-bitrate robot, and an earnest but off-key folk singer.\n[VOCAL EFFECTS]: Heavy "
            "bit-crushing, sudden aggressive gating, 'bad' scratching artifacts, extreme pitch "
            "modulation, abrupt dry cuts.\n[Instrumentation and Development]: Starts with "
            "aggressive IDM glitches, transitions to blast beats, into a comical tuba lead, "
            "followed by acoustic fingerpicking, ending with a shredding metal guitar solo.\n\n"
            "User Prompt:"
        ),
    },
}
# fmt: on

# Aliases for user convenience (CLI slugs)
PRESET_ALIASES: dict[str, str] = {
    "rap": "90s-rap",
    "90s rap": "90s-rap",
    "90's rap": "90s-rap",
    "latin": "latin-pop",
    "folk": "folk-ballad",
    "chiptune": "8-bit",
    "edm": "workout",
    "rnb": "rnb-romance",
    "r&b": "rnb-romance",
    "r&b romance": "rnb-romance",
    "kawaii": "kawaii-metal",
    "metal": "kawaii-metal",
    "orchestral": "cinematic",
    "ambient": "forest-bath",
    "kpop": "k-pop",
    "birthday": "birthday-roast",
    "roast": "birthday-roast",
    "country": "birthday-roast",
    "a cappella": "folk-a-cappella",
    "acappella": "folk-a-cappella",
    "cappella": "folk-a-cappella",
    "bad": "bad-music",
}


def get_music_preset(name: str) -> dict | None:
    """Look up a music style preset by name or alias.

    Returns the preset dict or None if not found.
    """
    key = name.lower().strip()
    # Direct lookup
    if key in MUSIC_PRESETS:
        return MUSIC_PRESETS[key]
    # Alias lookup
    if key in PRESET_ALIASES:
        return MUSIC_PRESETS[PRESET_ALIASES[key]]
    return None


def list_music_presets() -> list[str]:
    """Return sorted list of available preset keys."""
    return sorted(MUSIC_PRESETS.keys())


def build_preset_file_data(preset: dict) -> list:
    """Build the inner[0][9] file data structure for a music preset.

    Returns the array to assign to inner[0][9], which wraps the preset
    data at index [6] as the Gemini web UI does.
    """
    preset_id = preset["id"]
    return [
        None, None, None, None, None, None,
        [
            None, None, [],
            preset_id,
            [
                preset_id,
                preset["name"],
                [
                    [preset["image_url"], 1],
                    [preset["audio_url"], 3],
                ],
                preset["system_prompt"],
            ],
        ],
    ]
