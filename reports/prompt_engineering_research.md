# Gold Standard Prompt Engineering — Photorealistic AI Influencer

## 1. Photography Keywords That Eliminate the 'AI Look'

The AI look has three signatures: perfect symmetry, over-smoothed skin, and uncanny lighting.

**Camera & Lens (highest single-layer impact):**
```
shot on Sony A7IV, 85mm f/1.8, shallow depth of field, natural bokeh,
slight lens vignette, chromatic aberration, film grain ISO 400
```

**Lighting presets (select one per scenario):**
- Outdoor: `golden hour rim light, natural diffused daylight, soft shadow fill`
- Indoor: `practical light sources, window light, warm tungsten ambient`
- Studio: `3-point lighting, beauty dish key light, subtle hair light`

**Anti-perfection micro-detail:**
```
skin pores visible, natural skin texture, subtle asymmetry,
flyaway hair strands, micro-expressions, natural lip dryness
```

---

## 2. Authentic Vietnamese Feature Descriptors

Use precise anatomical terms — never generic ethnicity labels.

**Anatomical:**
```
single eyelid or subtle epicanthal fold, almond-shaped eyes,
high cheekbones with soft definition, straight nose bridge,
warm olive-golden undertone (Fitzpatrick III-IV),
naturally full lips with defined cupid's bow,
straight black hair with natural sheen
```

**Avoid:** `Asian, Oriental, exotic` — these produce generic AI stereotypes.

**Scenario-specific cultural markers:**
- Fashion: `contemporary Vietnamese street style, modern ao dai silhouette`
- Travel: `natural candid posture, authentic outdoor environment`
- Lifestyle: `natural makeup, no heavy contouring, fresh skin look`

---

## 3. Six-Layer Prompting Structure

```
[LAYER 1 — SUBJECT]
Vietnamese woman, mid-20s, [anatomical descriptors], [character trigger words]

[LAYER 2 — SCENARIO & ACTION]
[scenario], natural candid pose, [environment detail]

[LAYER 3 — STYLE & MOOD]
photorealistic, editorial photography, [mood: warm/cool/neutral]

[LAYER 4 — LIGHTING]
[lighting preset], soft shadows, no harsh flash

[LAYER 5 — CAMERA TECHNICAL]
shot on Sony A7IV, 85mm f/1.8, shallow DOF, film grain ISO 400, lens vignette

[LAYER 6 — QUALITY ANCHORS]
8K resolution, RAW photo, ultra detailed, skin pores visible,
subsurface scattering, natural skin imperfections
```

---

## 4. Negative Prompt Master List

```
# Quality Artifacts
(worst quality:1.4), (low quality:1.4), (normal quality:1.2),
lowres, jpeg artifacts, blurry, watermark, text, signature

# Plastic / AI Skin
(airbrushed skin:1.3), (plastic skin:1.3), smooth skin, perfect skin,
overprocessed, HDR, oversaturated, digital art, illustration, anime, CGI, 3D render

# Anatomy Errors
bad anatomy, bad hands, missing fingers, extra fingers, (six fingers:1.4),
malformed hands, mutated, deformed, extra limbs, cloned face, long neck

# Face Uncanny Valley
(fake eyes:1.3), glossy eyes, doll eyes, dead eyes, perfect symmetry,
no pores, waxy skin, heavy makeup, overdone contouring, caricature

# Lighting Artifacts
harsh shadows, flat lighting, blown highlights, overlit, rim light clipping
```

---

## 5. VisualArtist Agent Upgrade Plan

### `visual_artist.py` Changes

- [ ] Add `NEGATIVE_PROMPT_MASTER` as a module-level constant — immutable at runtime
- [ ] Replace current system prompt with full six-layer template + Vietnamese anatomical descriptors
- [ ] Add `camera_preset: Literal["outdoor", "indoor", "studio"]` to `WorkflowRequest`
- [ ] Output validation: assert response contains all 6 layer markers before forwarding to `WorkflowBuilder`
- [ ] Enforce system prompt caching at startup

### `CharacterProfile` Model Changes

- [ ] Add `feature_descriptors: list[str]` — replaces `trigger_words`
- [ ] Add `lighting_preset: Literal["outdoor", "indoor", "studio"]`
- [ ] Replace `negative_prompt: str` with `additional_negatives: list[str]`

### Integration Contract

```python
NEGATIVE_PROMPT_MASTER = (
    "(worst quality:1.4), (low quality:1.4), (airbrushed skin:1.3), "
    "(plastic skin:1.3), bad anatomy, bad hands, (fake eyes:1.3), "
    "perfect symmetry, waxy skin, 3D render, anime, illustration"
)

def build_negative(profile: CharacterProfile) -> str:
    extras = ", ".join(profile.additional_negatives) if profile.additional_negatives else ""
    return f"{NEGATIVE_PROMPT_MASTER}, {extras}".rstrip(", ")
```
