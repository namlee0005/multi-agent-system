import json

def parse_stream(stdout_raw):
    content_parts = []
    session_id = None
    input_tokens = 0
    output_tokens = 0

    for line in stdout_raw.strip().split('\n'):
        if not line.strip(): continue
        try:
            data = json.loads(line)
            if 'session_id' in data:
                session_id = data['session_id']
                
            if data.get('type') == 'assistant':
                msg = data.get('message', {})
                
                # capture usage
                usage = msg.get('usage', {})
                if usage:
                    input_tokens = max(input_tokens, usage.get('input_tokens', 0))
                    output_tokens = max(output_tokens, usage.get('output_tokens', 0))
                
                # Parse content blocks
                for block in msg.get('content', []):
                    if block.get('type') == 'text':
                        content_parts.append(block.get('text', ''))
                    elif block.get('type') == 'tool_use':
                        tool_name = block.get('name')
                        tool_input = block.get('input', {})
                        # If the agent used Write, format it as <write_file> so our reviewer sees it
                        if tool_name == 'Write':
                            filepath = tool_input.get('file_path', '')
                            file_content = tool_input.get('content', '')
                            content_parts.append(f'<write_file path="{filepath}">\n{file_content}\n</write_file>')
                        elif tool_name == 'Edit':
                            filepath = tool_input.get('file_path', '')
                            content_parts.append(f'[NATIVE_EDIT on {filepath} - CodeReviewer please verify on disk]')
                        else:
                            content_parts.append(f'[Used native tool {tool_name}]')
        except Exception as e:
            print("Error parsing line:", e)
            pass

    return '\n\n'.join(content_parts), session_id, input_tokens, output_tokens

# Test with a mock output
mock = """{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Write","input":{"file_path":"test.py","content":"print(1)"}}]}}"""
print(parse_stream(mock)[0])
