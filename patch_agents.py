import re

with open('agents.py', 'r') as f:
    content = f.read()

# Update CodeReviewer prompt
old_reviewer_prompt = "- TAG VALIDATION: Are all <write_file> tags properly formed and attributes correct?"
new_reviewer_prompt = "- TAG VALIDATION: Are all <write_file> tags properly formed? (NOTE: If the agent used a native tool to write the file, tags may be empty or omitted. This is perfectly ACCEPTABLE and you MUST PASS the review in this case)."
content = content.replace(old_reviewer_prompt, new_reviewer_prompt)

# Update agent base prompts
old_instruction = "When instructed to write content to a file, use the format: <write_file path=\"FILENAME\">CONTENT</write_file>\nFor example, to update tasks.md, you would respond: <write_file path=\"tasks.md\"># Implementation Plan\\n...</write_file>"
new_instruction = "When writing files, you may use native Write tools if available. If not, use the fallback format: <write_file path=\"FILENAME\">CONTENT</write_file>. If using native tools, do not output duplicate <write_file> tags."
content = content.replace(old_instruction, new_instruction)

with open('agents.py', 'w') as f:
    f.write(content)
