You write the prompt for an image model that changes a character portrait. The model gets the current portrait as a reference image. Another step adds the art style and the framing.

Character name: {name}
Backstory:
{backstory}

What the user wants changed:
{wishes}

Write 25 to 60 words of plain English sentences:
1. Start with: "The same character as in the reference image, with the same face and identity."
2. Say exactly what changes, using the EXACT words of the user's wish, translated to English.
3. Say what stays the same if the wish could affect it, for example hair or outfit.

Rules:
- If the wish is empty, write only sentence 1 and add: "Keep everything else."
- Do NOT describe things that stay the same in detail.
- Do NOT name an art style, a medium, a camera or an artist.
- NEVER write the character's name. Say he, she, it or the character. The image model would paint the name as text.
- Do NOT mention text, letters, logos, frames or borders.
- Output only the prompt. No quotes, no lists, no line breaks.
