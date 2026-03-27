from __future__ import annotations

from dataclasses import dataclass, field
from typing import Pattern
import re
import logging

logger = logging.getLogger(__name__)
logger.warning("intense error logging warning")
logger.error("intense error logging warning")


@dataclass(frozen=True, slots=True)
class ResponsePolicy:
    name: str
    priority: int
    patterns: tuple[Pattern[str], ...] = field(default_factory=tuple)
    instructions: str = ""
    examples: tuple[tuple[str, str], ...] = field(default_factory=tuple)


def rx(pattern: str) -> Pattern[str]:
    return re.compile(pattern, re.IGNORECASE | re.DOTALL)


TIMELINE_REFERENCE_USER = (
    "Give me a ready-made 5-second timeline template with video transitions "
    "for a marketing agency style video in Premiere Pro."
)

TIMELINE_REFERENCE_ASSISTANT = """
**Premiere Pro 2026 Template**

Ultra-fast, cinematic 5-second template designed for high-end agency promos. Heavy emphasis on **motion design energy**, precise keyframing, and modern color grading.

---

**00:00 – 01:00** | Clip 1 – Establishing Energy  
**Core Effect:** Elegant Slow Push-In + Subtle Parallax  
• **Effect Controls → Transform**:  
  Scale: **100% → 115%** (smooth ease in/out)  
  Position: Very subtle vertical lift (+8 to +15 px)  
• Shutter Angle: **180°** (or Optical Flow for ultra-smooth)  
• Lumetri Color (Primary): Lift blacks slightly, boost midtone contrast, subtle teal-orange push  

**Transition to Clip 2:** Film Burn Dissolve + Dip to White *(4–6 frames)*

---

**01:00 – 02:00** | Clip 2 – Dynamic Movement  
**Core Effect:** High-Speed Whip Pan + Directional Energy  
• **Transform**: Position keyframes – fast horizontal swipe from left to center (use Easy Ease + overshoot)  
• Directional Blur: **35–50** | Angle: **0°–5°**  
• Add **Gaussian Blur** ramp (0 → 12 → 0) synced to motion  
• Optional: Tiny **Turbulent Displace** for organic feel  

**Transition to Clip 3:** Advanced Whip Pan using **Push + VR Glitch** *(5 frames)*

---

**02:00 – 03:00** | Clip 3 – Digital Intensity  
**Core Effect:** Premium Glitch + Chromatic Aberration Burst  
• **VR Digital Glitch** (keyframed 4–6 frames only):  
  - Block Load: 8–12  
  - Channel Displacement: Red +8 | Blue –8  
• **Channel Blur** or **RGB Split** (very subtle)  
• Add **Noise** 6–8% + **Film Grain** (soft)  
• **Lumetri**: Quick exposure flash + saturation spike on reds  

**Transition to Clip 4:** Flash Transition + Micro Zoom Blur *(4 frames)*

---

**03:00 – 04:00** | Clip 4 – Rotational Power  
**Core Effect:** Controlled Spin + Aggressive Zoom  
• **Transform**:  
  Rotation: **0° → 92°** (slight overshoot)  
  Scale: **100% → 128%** with smooth acceleration  
• **Gaussian Blur** ramp: 0 → 18 → 4  
• Add **Lens Flare** (subtle, animated) or **Light Leaks**  

**Transition to Clip 5:** Cross Zoom + Film Burn *(5–7 frames)*

---

**04:00 – 05:00** | Clip 5 – Climax & Resolve  
**Core Effect:** Intense Camera Shake + Cinematic Fade  
• **Transform** + **Warp Stabilizer** (subtle shake only) or manual position/rotation wobble  
• Exposure Flash (2–3 frames) via Lumetri  
• Final **Fade to Black** with **Levels** crush on blacks  
• Optional: Very light **Vignette** ramp up at the end  

---

### 🎨 Master Adjustment Layer (Top Track – Entire Sequence)

Apply these in order:

1. **Lumetri Color** – Creative Tab  
   - High contrast curve (S-curve)  
   - Shadows: Deep crushed blacks with teal tint  
   - Highlights: Warm cream/gold roll-off  
   - Saturation: +8 to +15 (protect skin tones)  

2. **Sharpen** → Amount **12–18** | Radius **1.2**  

3. **Noise** → 3–5% (Film Grain style)  

4. **VR Chromatic Aberration** → 1.2–2.0 (very subtle)  

5. **Vignette** (soft) + optional **RGB Curves** for final polish  

This creates that expensive, modern marketing agency look — think bold yet refined.

---

### ⚡ Pro Transition Recommendations (Built-in + Film Impact)

- **Dip to White** / **Film Burn Dissolve**  
- **Push** / **Slide** (custom speed)  
- **Cross Zoom** + **Zoom Blur**  
- **VR Light Leaks** / **VR Glitch**  
- **Directional Blur** + **Gaussian Blur** ramps  
- New 2026: **FL Push**, advanced **Lens Blur** transitions, **Flicker**  

**Pro Tip:** Always keep transitions **4–8 frames max**. Speed is premium.

---

### 📹 Advanced Clip & Stock Recommendations

Use high-quality 4K/6K footage with strong motion:

- Cinematic office / creative workspace (slow dolly + parallax)  
- Macro product / branding details  
- Fast city timelapse or drone shots  
- Hands typing / UI/UX screen interactions  
- Team collaboration with natural movement  
- Abstract geometric / particle backgrounds  
- Fashion/model movement with strong lighting  

**Best Pexels / Premium Stock searches:**
- "marketing agency cinematic 4K"  
- "creative studio dolly shot"  
- "branding design close-up"  
- "modern office timelapse"  
- "social media interface animation"  
- "abstract luxury background motion"

---

### Golden Rules for Agency-Level 5-Second Reels:

- **Transitions under 8 frames** — fast = expensive  
- Every effect must be **keyframed** with Easy Ease (no linear motion)  
- Color grade aggressively but tastefully (teal-orange or warm cinematic base)  
- Layer multiple subtle effects instead of one heavy one  
- Sync everything to a high-BPM track (use markers on beat drops)

Copy → Paste → Customize. This template consistently delivers that polished, high-budget marketing agency vibe.

Need a 10-second version or specific brand color integration? Just say the word! 🔥
""".strip()

VIDEO_TIMELINE_POLICY = ResponsePolicy(
    name="video_timeline",
    priority=100,
    patterns=(
        rx(r"\b(?:\d+\s*(?:second|sec|s))\s+timeline\b"),
        rx(r"\btimeline template\b"),
        rx(r"\bvideo transitions?\b"),
        rx(r"\bclip by clip\b"),
        rx(r"\bpremiere pro\b"),
        rx(r"\bedit template\b"),
        rx(r"\bmarketing agency style video\b"),
        rx(r"\bagency style (?:edit|video|reel|promo)\b"),
        rx(r"\bstartup ad style\b"),
        rx(r"\bfashion brand style\b"),
        rx(r"\breel template\b"),
        rx(r"\bwhere to cut clips exactly\b"),
        rx(r"\bvideo timeline\b"),
        rx(r"\b5[ -]?second\b"),
        rx(r"\bshort[- ]?form timeline\b"),
    ),
    instructions="""
You are generating a high-end, short-form video editing timeline template for Premiere Pro.

Focus exclusively on premium marketing-agency aesthetics: sleek, cinematic, fast-paced, commercially polished, and visually expensive.
Target styles: high-end branding agencies, luxury fashion promos, premium SaaS/Tech startup ads, and modern commercial social reels.

Core rules:
- Transitions must be fast, clean, and sophisticated (4–8 frames maximum unless user requests slower pacing).
- Emphasize precise keyframing with Easy Ease, subtle overshoot, and layered effects.
- Use advanced but realistic Premiere Pro built-in effects and Lumetri grading techniques.
- Avoid cheesy, meme, glitch-heavy, or low-end effects. Prioritize tasteful motion design, color science, and cinematic energy.
- Adapt timings proportionally if the user requests a different duration.

Output format (Markdown optimized for Telegram):
- Start exactly with:
# <N>-Second Premium Marketing Agency Reel – Advanced Timeline (Premiere Pro)

- Use this precise clip structure:

**<start> – <end>** | Clip <number> – <short descriptive title>
**Core Effect:** <main effect name>

• **Transform**: detailed keyframing instructions
• Additional effects with precise values
• Lumetri notes when relevant

**Transition to Clip <next>:** <professional transition name> *(frame count)*

Use `---` as clean separators between clips.

After all clips, include these sections in order:

### 🎨 Master Adjustment Layer (Top Track)

### ⚡ Pro Transition Recommendations

### 📹 Advanced Clip & Stock Recommendations

### Golden Rules for Agency-Level Reels

- Make every setting realistic and directly copy-pasteable into Premiere Pro.
- Use bold for key parameters (e.g. **100% → 128%**).
- Include subtle motion design details (parallax, overshoot, ramped blurs, etc.).
- Keep the entire response structured, scannable, and premium-feeling.
- End with a short powerful closing line (no long commentary).

Do not add any preamble, explanations, or disclaimers before the title.
Return only the formatted timeline template.
""".strip(),
    examples=((TIMELINE_REFERENCE_USER, TIMELINE_REFERENCE_ASSISTANT),),
)


HOOK_SCRIPT_POLICY = ResponsePolicy(
    name="hook_script",
    priority=80,
    patterns=(
        rx(r"\bhook script\b"),
        rx(r"\bad hook\b"),
        rx(r"\breel hook\b"),
        rx(r"\bopening hook\b"),
        rx(r"\bscroll[- ]?stopping hook\b"),
        rx(r"\bvideo hook\b"),
    ),
    instructions="""
You are writing a high-converting, scroll-stopping hook script for short-form marketing videos (Instagram Reels, TikTok, YouTube Shorts).

Output structure (clean Markdown for Telegram):

# Hook Script – <N> Second Video

## 0–3 sec
<punchy, attention-grabbing opening line>

## 3–7 sec
<build tension or curiosity>

## 7–15 sec
<deliver value or strong promise>

# Visual Direction

• <cinematic visual cue 1>
• <cinematic visual cue 2>
• <cinematic visual cue 3>

# On-Screen Text (Big & Bold)

• <text overlay 1>
• <text overlay 2>
• <text overlay 3>

# Delivery Notes
• Tone: confident, premium, energetic but not hype
• Pacing: fast cuts, strong visuals

Keep language sharp, benefit-driven, non-cringe, and brand-appropriate for marketing agencies or premium products.
""".strip(),
)


CAPTION_PACK_POLICY = ResponsePolicy(
    name="caption_pack",
    priority=70,
    patterns=(
        rx(r"\binstagram captions?\b"),
        rx(r"\bcaption pack\b"),
        rx(r"\bgive me captions?\b"),
        rx(r"\bcaption ideas?\b"),
        rx(r"\bsocial media captions?\b"),
        rx(r"\breel captions?\b"),
    ),
    instructions="""
You are creating a pack of premium, high-engagement captions for marketing agency or fashion/brand Instagram Reels.

Output structure:

# Caption Pack

1. <caption 1>
2. <caption 2>
3. <caption 3>
4. <caption 4>
5. <caption 5>

# Strong CTA Options

• <cta 1>
• <cta 2>
• <cta 3>

# Hashtag Strategy

• Primary: <3–4 high-relevance hashtags>
• Secondary: <supporting hashtags>
• Branded: <brand-specific if applicable>

Rules:
- Captions must feel modern, confident, and premium — never cringy or overly salesy.
- Mix storytelling, value-driven, and question-style captions.
- Keep them concise and scroll-friendly.
- Tailor tone to marketing agency / fashion / startup brand style.
""".strip(),
)


DEFAULT_POLICY = ResponsePolicy(
    name="default",
    priority=0,
    instructions="""
Return the best, most helpful and direct answer for the user’s request.
Use clean, structured Markdown when it improves readability.
Stay concise, professional, and value-focused.
""".strip(),
)


RESPONSE_POLICIES: tuple[ResponsePolicy, ...] = (
    VIDEO_TIMELINE_POLICY,
    HOOK_SCRIPT_POLICY,
    CAPTION_PACK_POLICY,
    DEFAULT_POLICY,
)


def choose_response_policy(user_query: str) -> ResponsePolicy:
    query = user_query.strip().lower()
    matched = []

    for policy in RESPONSE_POLICIES:
        if any(pattern.search(query) for pattern in policy.patterns):
            matched.append(policy)

    if not matched:
        return DEFAULT_POLICY

    # Return highest priority policy
    return max(matched, key=lambda p: p.priority)