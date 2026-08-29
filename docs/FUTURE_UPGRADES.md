# VOLT CORE — Future Upgrades

## Vision
VOLT CORE evolves from an AI operations center into a multimodal personal command system. The core principle remains: observe, understand, communicate, request approval, and act only within explicit safety boundaries.

## Future Interface Layer
The interface will later support a live humanoid/energy visualization inspired by the visual references collected during product planning.

### Target capabilities
- Motion tracking from camera input.
- Responses to gestures.
- Live animated humanoid or abstract VOLT avatar.
- Reactive particle system that changes with VOLT state and mode.
- Ambient background and body animation.
- Sound effects and optional voice visualization.
- Desktop and mobile command center views.

## Important Architecture Decision
The visual avatar must be separated from the operational core.

`VOLT UI/AVATAR -> VOLT CORE API -> Watch / Approvals / Action Gate / Voice`

The avatar is an interface and must not receive direct authority to execute production actions. It communicates with the same authenticated API used by the dashboard.

## Proposed Modules

### VOLT PRESENCE
Owns avatar rendering, animations, particles, sound and state visualization.

### VOLT VISION
Processes camera input locally when possible. Gesture recognition should use explicit permission and provide an obvious camera-off state.

### VOLT VOICE
Real-time voice conversation, telephone calls, speech-to-text, text-to-speech and approval capture.

### VOLT MEMORY
Stores relevant operational context, decisions and user-approved preferences. Sensitive data must remain private and access-controlled.

### VOLT AUTOMATION
Controls approved integrations and devices through the Action Gate. No direct production execution without the existing safety policy.

## Avatar State Model
Initial states should include:
- idle
- listening
- thinking
- speaking
- working
- approval_required
- warning
- critical
- offline
- privacy_mode

Each state may change particles, movement, sound and dashboard lighting without changing VOLT's underlying permissions.

## Motion and Gesture Safety
Gesture input should be treated as a user interface, not as automatic authorization for sensitive actions. Critical operations should require explicit confirmation through voice, dashboard, phone or another authenticated approval channel.

## Phased Delivery
1. Current phase: secure backend, integrations, Watch, approvals and Action Gate.
2. Next phase: real voice and telephone provider.
3. Presence phase: animated VOLT avatar and state visualization.
4. Vision phase: local motion tracking and gesture controls.
5. Device phase: selected device and automation integrations.
6. Advanced phase: multimodal conversational command center.

## Design Principle
Build the useful infrastructure first. The humanoid interface becomes a controlled presentation layer over a stable and auditable core, not the other way around.
