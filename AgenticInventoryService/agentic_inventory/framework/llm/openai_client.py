"""
Azure OpenAI client for the HGV Framework.
"""

import json
from openai import AzureOpenAI
from agentic_inventory.utils import config
from agentic_inventory.utils.extensions import logger
from agentic_inventory.framework.utils.token_counter import token_counter_instance as token_counter
from agentic_inventory.framework.llm.llm_mngmt import llm_client


def get_openai_client() -> AzureOpenAI:
    """Get an OpenAI client instance."""
    if not config.AZURE_OPENAI_API_KEY.get_secret_value() or not config.AZURE_OPENAI_ENDPOINT:
        error_msg = (
            "Azure OpenAI credentials not found in environment variables. "
            "Please set AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT."
        )
        logger.error("[OPENAI ERROR] " + error_msg)
        raise ValueError(error_msg + " See .env.sample for an example configuration.")

    try:
        # client = AzureOpenAI(
        #     api_key=config.AZURE_OPENAI_API_KEY.get_secret_value(),
        #     api_version=config.AZURE_OPENAI_API_VERSION,
        #     azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
        # )
        # logger.info(f"Framework Client started model {config.AZURE_OPENAI_ENDPOINT}")
        return llm_client.get_llm()
    except Exception as e:
        logger.error(f"Failed to initialize LLM: {str(e)}")
        raise


def get_openai_response(prompt, system_message=None, json_mode=True, model_name=None):
    """Get response from Azure OpenAI.

    Args:
        prompt (str): The prompt to send to the LLM
        system_message (str): Optional system message to set context for the LLM
        json_mode (bool): Whether to request JSON formatted output
        model_name (str): The model to use (overrides env variable)

    Returns:
        dict: The parsed JSON response from the LLM
    """
    # Log key details for debugging
    logger.info("[OPENAI REQUEST] Endpoint: " + config.AZURE_OPENAI_ENDPOINT)
    logger.info("[OPENAI REQUEST] JSON mode: " + str(json_mode))
    logger.info("[OPENAI REQUEST] Prompt length: " + str(len(prompt)) + " characters")
    logger.info("[OPENAI REQUEST] Prompt first 100 chars: " + prompt[:100] + "...")

    try:
        client = get_openai_client()

        # When using json_mode, we need to include the word "json" in the prompt
        if json_mode:
            if "json" not in prompt.lower():
                prompt = prompt + "\n\nRespond with a JSON object."

        messages = []

        # Add system message if provided
        if system_message:
            messages.append({"role": "system", "content": system_message})

        # Add user prompt
        messages.append({"role": "user", "content": prompt})

        # Count tokens in the prompt
        token_counter.add_prompt(messages)

        response_format = {"type": "json_object"} if json_mode else None
        model = model_name or config.AZURE_OPENAI_MODEL_NAME

        logger.info("[OPENAI REQUEST] Sending request to model: " + model)

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format=response_format,
            temperature=0.0,
            top_p=1.0,
            max_tokens=None,  # Let the model decide
            stream=False,
            stop=None,
        )

        response_content = response.choices[0].message.content
        logger.info("[OPENAI RESPONSE] Received response of length: " + str(len(response_content)))
        logger.info("[OPENAI RESPONSE] First 100 chars: " + response_content[:100] + "...")

        # Count tokens in the response
        token_counter.add_response({"role": "assistant", "content": response_content})

        if json_mode:
            try:
                response_json = json.loads(response_content)
                logger.info("[OPENAI RESPONSE] Successfully parsed JSON response")
            except json.JSONDecodeError as e:
                error_msg = "Response was not valid JSON despite json_mode=True: " + str(e)
                logger.error("[OPENAI ERROR] " + error_msg)
                logger.error("[OPENAI ERROR] Raw response: " + response_content)
                response_json = {"error": "Invalid JSON", "raw_response": response_content}
        else:
            response_json = {"response": response_content}
            logger.info("[OPENAI RESPONSE] Returning non-JSON response")

        # Show token usage for this call
        prompt_tokens = sum(token_counter.count_tokens(msg["content"]) for msg in messages)
        response_tokens = token_counter.count_tokens(response_content)
        logger.info("[OPENAI TOKENS] Input: " + str(prompt_tokens) + ", Output: " + str(response_tokens))

        return response_json

    except Exception as e:
        import traceback

        error_details = traceback.format_exc()
        logger.error("[OPENAI ERROR] Error calling OpenAI API: " + str(e))
        logger.error("[OPENAI ERROR] Stack trace: " + error_details)

        # Return a structured error response
        return {"error": str(e), "response": "Error communicating with AI service", "details": error_details}


def query_llm(question, system_message=None):
    """Simplified function to query LLM with a question.

    This wrapper makes it easier to use in function compositions.

    Args:
        question (str): The question to ask the LLM
        system_message (str): Optional system message to set context for the LLM

    Returns:
        str: The LLM's response text (not as JSON)
    """
    prompt = "Please answer this question concisely: " + question
    response = get_openai_response(prompt, system_message=system_message, json_mode=False)
    return response["response"]


def generate_content(content_type, topic, length="short", system_message=None):
    """Generate specific content using the LLM.

    Args:
        content_type (str): Type of content (e.g., "blog", "email", "summary")
        topic (str): The topic to write about
        length (str): Desired length ("short", "medium", "long")
        system_message (str): Optional system message to set context for the LLM

    Returns:
        dict: Generated content with title and body
    """
    prompt = (
        "Generate a "
        + length
        + " "
        + content_type
        + " about "
        + topic
        + ".\n"
        + "Return a JSON with the following structure:\n"
        + "{\n"
        + '    "title": "An engaging title",\n'
        + '    "content": "The generated '
        + content_type
        + ' content"\n'
        + "}"
    )

    response = get_openai_response(prompt, system_message=system_message, json_mode=True)
    return response
