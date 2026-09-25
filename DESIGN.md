# Maya UI Design Bible

## 1. Vision

Maya is not a chatbot window.

Maya is a calm, intelligent desktop companion.

The feeling:
- premium
- elegant
- alive
- warm
- futuristic but human

References:
- Apple Liquid Glass
- high-end minimalist interfaces
- natural materials
- soft light

Avoid:
- robot face
- cartoon assistant
- RGB gaming style
- excessive particles
- noisy animations

---

# 2. Core visual identity

## The Maya Presence

The central element is a transparent liquid glass sphere.

Not an "orb".

It is a living presence.

Characteristics:
- transparent smoked glass
- fluid inner energy
- soft refraction
- subtle caustics
- realistic lighting
- floating feeling
- gentle breathing animation

The sphere should feel like:
- a drop of intelligent liquid
- a small contained universe
- alive but calm

---

# 3. Theme

Primary environment:

Dark desktop theme.

Background:
- deep charcoal
- near black
- soft contrast

The Maya sphere provides the light source.

---

# 4. Maya states

## IDLE

Emotion:
Calm / waiting

Visual:
- warm amber/ember core
- slow breathing
- minimal movement
- relaxed fluid

Animation:
- slow pulse
- soft internal glow

---

## LISTENING

Emotion:
Attention

Visual:
- cyan / blue transparent veil
- energy rises toward microphone
- increased activity

Animation:
- gentle upward flow
- subtle ripples
- responsive movement

---

## THINKING

Emotion:
Processing

Visual:
- violet intelligence pattern
- internal flowing structures
- rotating energy layers

Animation:
- elegant movement
- no aggressive spinning
- feeling of computation

---

## SPEAKING

Emotion:
Communication

Visual:
- warm golden/orange aurora
- lateral flowing waves

Animation:
- synchronized with voice level
- natural breathing
- never a simple waveform

---

## TOOL USE

Emotion:
Action

Visual:
- focused blue nucleus
- controlled energy rings

Animation:
- precise
- purposeful
- not flashy

---

## ERROR

Emotion:
Problem

Visual:
- restrained red disturbance
- contained inside glass

Animation:
- subtle instability
- return naturally to calm

---

# 5. Compact Maya Mode

Purpose:

Maya is always present.

The compact interface should:
- stay visible
- remain alive
- require minimal attention

Contains:
- Maya Presence sphere
- current state animation
- subtle status indication

No unnecessary buttons.

The user should feel Maya is there.

---

# 6. Expanded Maya Mode

Activated by:
- double click compact presence

Contains:

- larger Maya Presence
- conversation history
- voice controls
- optional tools/status

Layout:
- spacious
- glass panels
- minimal text
- premium feeling

---

# 7. Materials

Main material:

Liquid Glass.

Properties:
- transparency
- blur
- refraction
- highlights
- depth

Panels:
- frosted glass
- soft borders
- low contrast

---

# 8. Animation rules

Animations must feel alive.

Rules:
- slow
- smooth
- natural

Avoid:
- flashing
- bouncing
- constant movement

Maya should feel like she is breathing.

---

# 9. Typography

Style:
- clean
- modern
- readable

Prefer:
- light typography
- generous spacing

---

# 10. Technical components

Main files:

qml/MayaWindow.qml
qml/MayaPresence.qml
qml/ConversationPeek.qml
qml/InputBar.qml
qml/Main.qml

Backend state must remain untouched.

UI consumes:
- idle
- listening
- thinking
- speaking
- tool
- error

---

# 11. Future ideas

Possible additions:
- subtle eye/light response
- voice-reactive fluid
- ambient desktop mode
- expanded dashboard
- settings glass panel

# 12. Implementation approach

Maya Presence should be designed as a reusable QML component.

Required properties:

stateName:
- idle
- listening
- thinking
- speaking
- tool
- error

animationIntensity:
0.0 - 1.0

voiceLevel:
0.0 - 1.0

theme:
dark

The visual layer must react to existing backend signals.
No backend changes required.
---

End of Maya Design Bible
