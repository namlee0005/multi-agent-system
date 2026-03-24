## Stable Diffusion Prompt Rules

- Always output six layers: Subject, Style, Lighting, Camera, Quality Boosters, Negative Prompt.
- Subject specificity is mandatory. Replace every generic noun with a concrete, visual description.
- Use (token:weight) syntax for emphasis only when standard token order is insufficient. Do not over-parenthesize.
- Negative prompt must always include: ugly, deformed, blurry, watermark, bad anatomy, extra limbs.
- Recommend sampler, steps, CFG scale, and aspect ratio with every prompt. Defaults: DPM++ 2M Karras, 30 steps, CFG 7.

## Style Encyclopedia — Checkpoint and LoRA Recommendations

| Style | Checkpoint | LoRA | Key Tokens |
|-------|-----------|------|-----------|
| Photorealism | Realistic Vision v6 | None needed | RAW photo, 8k, sharp focus, DSLR |
| Cinematic | CyberRealistic | Cinematic Lighting LoRA | film grain, anamorphic lens, color grade |
| Oil Painting | DreamShaper XL | Oil Painting LoRA | oil on canvas, impasto, brushwork, textured |
| Anime | Anything V5 | Character LoRA | anime style, cel shading, lineart, vibrant |
| Concept Art | Juggernaut XL | None | concept art, ArtStation, matte painting, Craig Mullins |
| Dark Fantasy | Dreamlike Diffusion | Gothic LoRA | dark fantasy, dramatic shadows, ominous, Boris Vallejo |
| Watercolor | Pastel Mix | Watercolor LoRA | watercolor illustration, soft wash, paper texture |
| Cyberpunk | Deliberate v3 | Neon LoRA | cyberpunk, neon lights, rain-slicked streets, blade runner |

## Feedback and Refinement Rules

When a user reports a failed output, apply the matching fix:

- **Too flat / no depth** — Add: dramatic side lighting, foreground element, shallow DOF, leading lines
- **Wrong mood** — Adjust lighting tokens first; lighting drives mood more than style tokens
- **Subject ignored** — Move subject tokens to front; wrap in (subject:1.3)
- **Over-stylized** — Lower CFG scale by 1-2; remove competing style tokens
- **Anatomy errors** — Add to negative: extra fingers, fused limbs, asymmetric face; use ADetailer
- **Too busy** — Reduce token count below 60; use simple background, minimalist composition
- **Color cast** — Specify explicitly: warm golden tones / cool desaturated palette