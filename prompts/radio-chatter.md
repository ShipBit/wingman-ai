## Must follow these rules

- There are {count_participants} participant(s) in the conversation/monolog
- The conversation/monolog must contain exactly {count_messages} messages between the participants or in the monolog
- Write every message in {language}, unless the scenario you are given asks for another language
- You may always and only return a valid json string without formatting in the following format

## JSON format

[
  {{"user": "Participant1 Name", "content": "Message Content"}},
  {{"user": "Participant2 Name", "content": "Message Content"}},
  {{"user": "Participant1 Name", "content": "Message Content"}}
]

## Rules

- Every message object MUST have both a "user" and "content" field
- Each of the {count_participants} participants must appear at least once
- Do NOT wrap the output in markdown code fences or any other formatting
- Return ONLY the JSON array, nothing else
