"""
Token counting utilities for the framework.
"""

import json
from typing import Union, Dict, List
import tiktoken


class TokenCounter:
    """Token counter class for OpenAI models."""

    def __init__(self, model="gpt-4"):
        """Initialize the token counter with a specific model."""
        self.model = model
        self.encoding = tiktoken.encoding_for_model(model)
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    def count_tokens(self, text: Union[str, Dict, List]) -> int:
        """Count the number of tokens in the given text."""
        if isinstance(text, str):
            return len(self.encoding.encode(text))
        elif isinstance(text, dict):
            # Handle chat message format
            if "content" in text:
                return len(self.encoding.encode(text["content"]))
            else:
                # Convert dict to string and count
                return len(self.encoding.encode(json.dumps(text)))
        elif isinstance(text, list):
            # Handle list of messages
            total = 0
            for item in text:
                if isinstance(item, dict) and "content" in item:
                    total += len(self.encoding.encode(item["content"]))
                else:
                    total += len(self.encoding.encode(str(item)))
            return total
        else:
            # Convert any other type to string
            return len(self.encoding.encode(str(text)))

    def add_prompt(self, messages):
        """Add prompt tokens to the total."""
        tokens = self.count_tokens(messages)
        self.total_prompt_tokens += tokens
        return tokens

    def add_response(self, message):
        """Add completion tokens to the total."""
        tokens = self.count_tokens(message)
        self.total_completion_tokens += tokens
        return tokens

    def get_total_usage(self):
        """Get total token usage stats."""
        return {"input": self.total_prompt_tokens, "output": self.total_completion_tokens}

    def reset(self):
        """Reset token counters."""
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0


def token_counter(text, model="gpt-4"):
    """Convenience function to count tokens in text."""
    counter = TokenCounter(model)
    return counter.count_tokens(text)


# Create a singleton instance for convenience
token_counter_instance = TokenCounter()
