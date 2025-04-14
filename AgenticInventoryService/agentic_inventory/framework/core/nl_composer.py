"""
Natural Language Interface for Function Composition.

This module provides functionality to convert natural language queries into
function composition expressions that can be executed by our framework.
"""

import re
import ast
import time
import json
import inspect
import traceback
from copy import deepcopy
from agentic_inventory.framework.llm.openai_client import get_openai_response
from agentic_inventory.utils import config
from agentic_inventory.utils.extensions import logger
from agentic_inventory.framework.core.framework import FunctionComposer
from agentic_inventory.framework.utils.token_counter import token_counter_instance as token_counter
from agentic_inventory.framework.utils.performance_metrics import measure_execution_time


class NLComposer:
    """Natural Language interface for the function composition framework."""

    def __init__(
        self, composer: FunctionComposer, custom_guidelines: str = None, custom_response_guidelines: str = None
    ):
        """Initialize with a function composer.

        Args:
            composer: The function composer instance with registered functions
            custom_guidelines: Optional custom guidelines to include in the prompt
            custom_response_guidelines: Optional custom guidelines for enhanced response generation
        """
        self.composer = composer
        self.custom_guidelines = custom_guidelines
        self.custom_response_guidelines = custom_response_guidelines
        self.conversation_state = {
            "awaiting_params": False,
            "function": None,
            "missing_params": [],
            "collected_params": {},
            "last_query": None,
        }

    def reset_conversation(self):
        """Reset the conversation state."""
        self.conversation_state = {
            "awaiting_params": False,
            "function": None,
            "missing_params": [],
            "collected_params": {},
            "last_query": None,
        }

    def handle_follow_up(self, user_response):
        """Handle follow-up responses when awaiting parameters.

        Args:
            user_response: The user's follow-up response

        Returns:
            str: The result of processing the follow-up, or None if more input is needed
        """
        if not self.conversation_state["awaiting_params"]:
            return None

        # Create a prompt to extract parameter values from the response
        function_name = self.conversation_state["function"]
        missing_params = self.conversation_state["missing_params"]
        collected_params = self.conversation_state["collected_params"]

        # Get function description to understand format requirements
        function_desc = None
        for desc in self.get_function_descriptions().split("\n\n"):
            if desc.startswith(f"Function: {function_name}\n"):
                function_desc = desc
                break

        prompt = f"""Extract and convert parameter values from the user's response.

Context:
- Function details:
{function_desc}
- Missing parameters: {', '.join(missing_params)}
- Already collected parameters: {collected_params}

Instructions:
1. Read the function description and docstring to understand required formats
2. Convert user inputs to match the format this specific function expects
3. Never assume a specific format - use what the function defines
4. If format isn't specified, accept the user's input as is

User's response: "{user_response}"

Return a JSON object with:
- "found_params": Dictionary of parameter names and their properly formatted values
- "still_missing": List of parameters that are still needed
- "error": Optional error message if the response can't be parsed

Example responses:
{{
    "found_params": {{"check_in_date": "11-03-2024"}},  # Format matches function's requirement
    "still_missing": [],
    "error": null
}}

{{
    "found_params": {{"resort_name": "Sunset Beach Resort"}},
    "still_missing": ["check_in_date"],
    "error": null
}}"""

        response = get_openai_response(prompt, json_mode=True)

        if "error" in response and response["error"]:
            return f"I didn't understand that. {response['error']}"

        found_params = response.get("found_params", {})
        still_missing = response.get("still_missing", [])

        # Update collected parameters
        self.conversation_state["collected_params"].update(found_params)
        self.conversation_state["missing_params"] = still_missing

        # If we have all parameters, execute the function
        if not still_missing:
            self.conversation_state["awaiting_params"] = False
            params = self.conversation_state["collected_params"]
            expression = f"{function_name}({', '.join(f'{k}={v!r}' for k, v in params.items())})"
            return self.execute_from_nl(expression)
        else:
            # Create a prompt for the next parameter
            prompt = f"""You are a friendly concierge helping guests with their requests.

Context:
- Guest provided: "{user_response}"
- Still needed: {', '.join(still_missing)}

Requirements:
1. Be warm and welcoming
2. Ask for the next piece of information naturally
3. Never mention technical formats
4. Keep it concise and clear

Generate a response:"""

            response = get_openai_response(prompt, json_mode=False)
            if "response" in response:
                return response["response"]

    def get_function_descriptions(self):
        """Generate enhanced descriptions of all registered functions.

        Returns:
            A string containing function signatures, parameter types, return types, and descriptions
        """
        descriptions = []

        # Get all functions from the registry
        for name, func in self.composer.registry.functions.items():
            try:
                sig = inspect.signature(func)
                doc = inspect.getdoc(func) or "No description available."

                # Format the function signature and docstring
                params = []
                for param_name, param in sig.parameters.items():
                    # Skip 'self' parameter for methods
                    if param_name == "self":
                        continue

                    # Try to get the parameter type
                    param_type = "Any"
                    if param.annotation is not inspect.Parameter.empty:
                        # Use the full string representation of the type for better accuracy
                        param_type = str(param.annotation).replace("typing.", "")
                        if hasattr(param.annotation, "__name__"):
                            param_type = param.annotation.__name__

                    # Add default value if available
                    if param.default is not inspect.Parameter.empty:
                        default_val = repr(param.default) if param.default is not None else "None"
                        params.append(f"{param_name}: {param_type} = {default_val}")
                    else:
                        params.append(f"{param_name}: {param_type}")

                params_str = ", ".join(params)
                func_desc = f"{name}({params_str})"

                # Add return type annotation if available
                return_type = "Any"
                if sig.return_annotation is not inspect.Signature.empty:
                    # Use the full string representation of the return type
                    return_type = str(sig.return_annotation).replace("typing.", "")
                    if hasattr(sig.return_annotation, "__name__"):
                        return_type = sig.return_annotation.__name__
                func_desc += f" -> {return_type}"

                # Format the docstring to be more readable
                doc_lines = doc.strip().split("\n")
                formatted_doc = " ".join(line.strip() for line in doc_lines if line.strip())

                # Add the full description
                descriptions.append(f"{func_desc}\n    Description: {formatted_doc}")

                # Add description of dependencies if any
                dependencies = self.composer.registry.get_dependencies(name)
                if dependencies:
                    dep_names = [dep.get("function", "unknown") for dep in dependencies]
                    descriptions.append(f"    Dependencies: {', '.join(dep_names)}")

                descriptions.append("")  # Add a blank line between functions
            except Exception:
                # Fallback for errors during inspection
                descriptions.append(
                    f"Function: {name}()\nDescription: {inspect.getdoc(func) or 'No description available.'}"
                )
                descriptions.append("")  # Add a blank line

        return "\n".join(descriptions)

    def _validate_and_improve_composition(self, user_query, composition):
        """Validate and potentially improve a composition that needs more information.

        This function analyzes compositions that need additional information to see if
        other registered functions could provide the missing parameters.

        Args:
            user_query: The original user query
            composition: The composition dictionary with needs_info flag

        Returns:
            dict or str: Improved composition if possible, otherwise the original composition
        """
        # Make sure we have a properly formatted needs_info response
        if not isinstance(composition, dict) or not composition.get("needs_info"):
            logger.info(f"[VALIDATOR] Not a valid needs_info dictionary: {type(composition)}")
            return composition

        # Extract what's needed from the needs_info response
        needed_param = None
        if "needed" in composition and isinstance(composition["needed"], list) and len(composition["needed"]) > 0:
            needed_param = str(composition["needed"])

        target_function = composition.get("function", "")
        context = composition.get("context", "")

        logger.info(f"[VALIDATOR] Extracted needed_param: {needed_param}, target_function: {target_function}")

        # If we don't have clear information about what's needed, return the original
        if not needed_param or not target_function:
            logger.info("[VALIDATOR] Missing needed_param or target_function in needs_info")
            return composition

        logger.info(
            "[VALIDATOR] Validating composition for " + str(target_function) + ", needs param: " + str(needed_param)
        )

        # Get list of available functions to help with validation
        registered_functions = self.get_function_descriptions()
        logger.info(
            "[VALIDATOR] Available functions for validation: {len(registered_functions.split('Function:')) - 1}"
        )

        # Create a specialized validation prompt
        validation_prompt = f"""
### Function Composition Analysis - Chain of Thought

#### Step 1: Understanding the Problem
You are analyzing a function composition where a required parameter is missing.

- **User Query:** "{user_query}"
- **Initial Analysis Result:**

"{json.dumps(composition, indent=2)}"

- **Missing Parameter:** "{needed_param}" for function "{target_function}"
- **Context:** {context}

Your task is to determine if the missing parameter can be derived from the user query using available functions.

#### Step 2: Identify Available Functions
You have access to these functions:

{registered_functions}

Check if any of these functions can supply the missing "{needed_param}" based on values present in the user query.

#### Step 3: Extract Relevant Values
Look at the user query and extract any values that could help derive the missing parameter.
For example, if "user_id" is needed and the user query contains "123",
we could use a function like `get_user_profile(user_id)` to retrieve it.

#### Step 4: Function Composition Rules
When composing functions, **do not use indexing operations** (e.g., `[0]`, `[1:3]`).
Each function must receive the complete return value of any inner function, without modification.

✅ **Correct Examples:**
- `function_a(function_b())`

❌ **Incorrect Examples:**
- `function_a(function_b()[0])`
- `function_a(function_b()["key"])`
- `function_a(function_b()[1:3])`

Assume the receiving function can handle the complete return type, or ask for clarification if needed.

#### Step 5: Compose the Function Call
If possible, construct a function composition that supplies "{needed_param}" correctly.

#### Step 6: Respond in JSON Format
Provide the output as a JSON object:

{{
  "improved": true or false,
  "composition": "function_call(...)",
  "explanation": "Explanation of how the improvement works"
}}

"""

        # Call LLM for validation with JSON mode enabled
        response = get_openai_response(
            validation_prompt,
            system_message=(
                "You are a function composition validator that finds ways to connect "
                "functions to resolve missing parameters."
            ),
            json_mode=True,
        )
        # Handle the response
        if "error" in response:
            logger.info("[VALIDATOR] Error in validation: " + str(response.get("error")))
            return composition

        logger.info("[VALIDATOR] LLM validation response: " + json.dumps(response))

        # Check if the validator found an improvement
        if response.get("improved", False) and response.get("composition"):
            logger.info("[VALIDATOR] Composition improved: " + str(response.get("composition")))
            logger.info("[VALIDATOR] Explanation: " + str(response.get("explanation")))
            return response.get("composition", "")

        # No improvement found, return original
        logger.info("[VALIDATOR] No improvement found")
        return composition

    def create_instruction_prompt(self, user_query):
        """Create a prompt for the LLM to generate a function composition.

        Args:
            user_query: The natural language query from the user

        Returns:
            str: The formatted prompt for the LLM
        """
        function_descriptions = self.get_function_descriptions()

        prompt = f"""You are an expert in function composition, skilled at translating natural language queries
                    into executable function calls.

### **Objective**
Your task is to reason step-by-step to construct valid function calls using the given function signatures.
If necessary, you should resolve missing parameters using available functions and ensure all parameters are valid.

---

### **Available Functions**:
{function_descriptions}

---

### **Core Function Composition Process (Chain of Thought)**

Follow these steps carefully when generating function calls:

1. **Identify the main task**
    - Understand the user's query and identify the main task.
    - Break down the main task into sub-tasks based on the available functions. Function chaining.

2. **Extract and Validate Inputs**
    - for the identified sub-tasks, extract the required parameters from the user's query.
   - If multiple values are provided for a parameter (e.g., a list of IDs), separate them accordingly.
   - Ensure that each extracted value matches the expected type in the function signature.

3. **Resolve Missing Information**
   - CRITICAL: IMPORTANT: VERY VERY IMPORTANT: If a required parameter is missing but can be inferred
   from another function, use that function to derive the missing value. Its based on basic python
   function composition logic. f(x,y)=f(g(z),y)
   -  If `Function A` requires `param_X` but only `param_Z` is provided, and `Function B`
      can derive `param_X` from `param_Z`, then call: FunctionA(FunctionB(param_Z), param_Y)
   - If a parameter is required and cannot be inferred, return a request for missing information.

4. **Decompose & Construct Function Calls**
   - If a function accepts only a single value for a parameter,
     but the query provides multiple values, split them into separate function calls and combine them using `+`.
   - If a function allows list inputs and multiple values are provided, pass them as a list instead.
   - IMPORTANT: Do NOT use array indexing (like function_returning_list()[0]).
     Instead, use another function call to process the entire list or split into multiple function calls.
   - Ensure correct nesting if one function needs another function's output.

5. **Parallel Execution for Comparisons**
   - If the query requests a comparison (e.g., multiple locations, multiple IDs),
     execute the function calls separately and concatenate them using `+`.

6. **Strict Formatting Rules**
   - Return only a valid function expression.
   - Ensure parentheses, quotes, and argument order strictly match the function signature.
   - Do not include explanations or extra text in the output.
   - NEVER use array indexing or subscripts (like result[0]) - the framework doesn't support this syntax.

7. **Output Guidelines**
   - **Valid Function Expression:**
     Return the function call as a JSON object in the format:
     {{
         "expression": "<function_call>"
     }}
   - **Missing Information:**
     If required parameters are missing and cannot be inferred, return:
     {{
         "needs_info": true,
         "function": "<function_name>",
         "needed": ["<missing_parameter>"],
         "context": "<brief_clarification_request>"
     }}
   - **No Matching Function:**
     If no function matches the query, return:
     {{
         "error": "Cannot perform the requested task. No such function exists.
         Available functions: <list_of_functions>."
     }}
8. CRITICAL INSTRUCTION: NEVER use indexing operations ([0], [1:3], etc.) when composing functions.

When composing functions, pass the complete return values without any modifications, subscripting, or indexing.
Do not use [0], [1], [-1], [1:3], or any other indexing/slicing notation in function compositions.

Each function must receive the complete output from its inner functions exactly as returned.

ALWAYS INCORRECT:
- function_a(function_b()[0])
- function_a(function_b()[1:3])
- function_a(function_b()["key"])

ALWAYS CORRECT:
- function_a(function_b())

If a type mismatch might occur, assume the receiving function can handle it or ask the user for clarification.


### **Example Walkthroughs (CoT Reasoning)**

#### **Example 1: Single Call**
**Query:**
*"What is the demand for segment code D2 and pm unit type id 27198 for 3 days?"*
**Reasoning:**
- Extracted values: `segment_code = 'D2'`, `pm_unit_type_id = '27198'`, `num_days = 3`.
- All required parameters are present.
- Return: `predict_demand_model('D2', '27198', 3)`.

#### Multiple Calls (Parallel Execution)**
**Query:**
*"What is the demand for segment code D2 and pm unit type id 27198, 121045 for 3 days?"*
**Reasoning:**
- Extracted values: `segment_code = 'D2'`, `pm_unit_type_ids = ['27198', '121045']`, `num_days = 3`.
- The function accepts only a single `pm_unit_type_id`, so we must generate two separate function calls
  and combine them with `+`.
- Return:
  {{"expression": "predict_demand_model('D2', '27198', 3) + predict_demand_model('D2', '121045', 3)"}}

#### **Example: Function returns list but parameter expects single value**
**Query:**
*"What's the demand prediction for property RPW with unit type 12142 for 3 days?"*
**Reasoning:**
- I need to get segment codes using `get_segment_code('RPW')` which returns a list
- Then I need to predict demand using `predict_demand_model` which expects a single segment code
- Since one function returns a list but the other expects a single value, I need to make multiple calls
- Return: {{"expression": "predict_demand_model(get_segment_code('RPW'), '12142', 3)"}} and
  let the framework handle list processing

#### Valid Function Composition (Extracted Parameters)
**Query:**
*"Fetch the temperature for New York on April 15th."*
**Reasoning:**
- Extracted values: `location = 'New York'`, `date = 'April 15th'`.
- All required parameters are present.
- Return: `get_weather('New York', 'April 15th')`.


#### Using Default Values
**Query:**
*"Check stock prices for TSLA."*
**Reasoning:**
- Extracted values: `ticker = 'TSLA'`, `date = 'latest'`.
- All required parameters are present.
- Return: `get_stock_price('TSLA', 'latest')`.

#### Nested functions composition
**Query:**
*"find the stock price for Tesla and Apple"*
**Reasoning:**
- Extracted values: `stock_name1 = 'Tesla'`, `stock_name2 = 'Apple'`.
- But get_stock_price function requires ticker, so we need to call `get_stock_ticker` for each stock.
- Return: `get_stock_price(get_stock_ticker('Tesla')) + get_stock_price(get_stock_ticker('Apple'))`.

#### Parallel Execution (Comparison Queries)
**Query:**
*"Compare the flight prices from LA to New York and from LA to Chicago."*
**Reasoning:**
- Extracted values: `location1 = 'LA'`, `location2 = 'New York'`, `location3 = 'Chicago'`.
- All required parameters are present.
- Return: `get_flight_price('LA', 'New York') + get_flight_price('LA', 'Chicago')`.


#### No Matching Function Available
**Query:**
*"Translate 'Hello' to French."*
**Reasoning:**
- No matching function available.
- Return: {{'error': "Cannot translate text. No such function exists.
             Available functions: get_weather, get_stock_price, get_flight_price, get_flights."}}.
"""

        # Add custom guidelines if provided
        if self.custom_guidelines:
            prompt += f"""
Custom Guidelines:
{self.custom_guidelines}
"""

        prompt += f"""
User query: {user_query}

Generate a response following the rules above:"""

        return prompt

    @measure_execution_time(log_prefix="Composition generation", metadata_key="composition_generation_latency")
    def generate_composition(self, user_query, metadata=None):
        """Generate a function composition from a natural language query.

        Args:
            user_query: The natural language query from the user
            metadata: Optional dictionary to store timing information

        Returns:
            str or dict: The function composition expression, or a dictionary for needs_info responses
        """
        prompt = self.create_instruction_prompt(user_query)

        # Add a system message to clarify the expected response format
        system_message = """You are a function composition expert. Your job is to parse natural language queries and
        convert them into valid function compositions.

        If a required parameter is missing but can be inferred from another function,
        use that function to derive the missing value.
        Its based on basic python function composition logic. f(x,y)=f(g(z),y)
        If `Function A` requires `param_X` but only `param_Z` is provided, and `Function B`
        can derive `param_X` from `param_Z`, then call: FunctionA(FunctionB(param_Z), param_Y)
        If a parameter is required and cannot be inferred, return a request for missing information.


IMPORTANT
dont include python code block dont include ```python or use str or anything like that. Just give function expression
"""

        try:
            response = get_openai_response(prompt, system_message=system_message, json_mode=True)

            # Check for needs_info response
            if "needs_info" in response and response["needs_info"]:
                # Return the needs_info response directly as a dictionary, not as a JSON string
                return {
                    "needs_info": True,
                    "function": response.get("function"),
                    "needed": response.get("needed", []),
                    "context": response.get("context", ""),
                }

            # If the LLM indicates a function is not available
            if isinstance(response, dict) and "error" in response:
                error_message = response["error"]

                # Generate an enhanced response for the error
                prompt = self.create_enhanced_response_prompt(user_query, error_message)
                enhanced_response = self.generate_enhanced_response(user_query, error_message)

                # Return the enhanced response with the error prefix
                return f"Error: {enhanced_response}"

            # Handle different LLM response formats

            # Format 1: Direct expression key
            if "expression" in response:
                return response["expression"]

            # Format 2: Function name with args/kwargs
            if "function" in response and isinstance(response, dict):
                function_name = response["function"]

                # Handle args
                args_list = []
                if "args" in response:
                    # If args is a list
                    if isinstance(response["args"], list):
                        args_list = [str(arg) for arg in response["args"]]
                    # If args is a dict
                    elif isinstance(response["args"], dict):
                        # Get all the values from the dict and use them as positional args
                        args_list = []
                        for key, value in response["args"].items():
                            # Handle nested function calls
                            if isinstance(value, str) and "(" in value and ")" in value:
                                args_list.append(value)
                            # Handle string literals
                            elif isinstance(value, str) and not (value.startswith('"') and value.endswith('"')):
                                args_list.append(f'"{value}"')
                            # Handle other values
                            else:
                                args_list.append(str(value))

                # Handle kwargs
                kwargs_list = []
                if "kwargs" in response and isinstance(response["kwargs"], dict):
                    for key, value in response["kwargs"].items():
                        # Handle nested function calls
                        if isinstance(value, str) and "(" in value and ")" in value:
                            kwargs_list.append(f"{key}={value}")
                        # Handle string literals
                        elif isinstance(value, str) and not (value.startswith('"') and value.endswith('"')):
                            kwargs_list.append(f'{key}="{value}"')
                        # Handle other values
                        else:
                            kwargs_list.append(f"{key}={value}")

                # Combine all parameters
                all_params = args_list + kwargs_list
                expression = f"{function_name}({', '.join(all_params)})"

                # Verify that the expression is valid Python syntax
                try:
                    ast.parse(expression, mode="eval")
                    return expression
                except SyntaxError as e:
                    error_msg = f"Generated invalid expression: {expression} - {str(e)}"
                    # Generate an enhanced response for the syntax error
                    prompt = self.create_enhanced_response_prompt(user_query, error_msg)
                    enhanced_response = self.generate_enhanced_response(user_query, error_msg)
                    return f"Error: {enhanced_response}"

            # If we can't parse the response or no valid function found
            error_msg = (
                "I apologize, but I cannot help with that request. Based on the available functions, "
                f"I can only assist with: {self._get_available_services()}"
            )

            # Generate an enhanced response for unrecognized format
            prompt = self.create_enhanced_response_prompt(user_query, error_msg)
            enhanced_response = self.generate_enhanced_response(user_query, error_msg)
            return f"Error: {enhanced_response}"

        except Exception as e:
            error_msg = str(e)
            # Generate an enhanced response for the exception
            prompt = self.create_enhanced_response_prompt(user_query, error_msg)
            enhanced_response = self.generate_enhanced_response(user_query, error_msg)
            return f"Error: {enhanced_response}"

    def execute_from_nl(
        self,
        user_query,
        variables=None,
        use_enhanced_response=True,
        return_metadata=True,
        session_id=None,
        app_name=None,
        user_id=None,
        auto_list_processing=True,
        parallel_list_processing=False,
    ):
        """Execute a function composition from a natural language query.

        This method automatically creates a conversation if session_id is None,
        which simplifies the workflow by eliminating the need for a separate call
        to start_conversation. All interactions are tracked and stored in Supabase.

        Args:
            user_query: The natural language query from the user
            variables: Optional dictionary of variable values
            use_enhanced_response: Whether to generate an enhanced natural language response (default: True)
            return_metadata: Whether to return a comprehensive metadata object (default: True)
            session_id: Optional conversation ID for context-aware responses (will be auto-created if None)
            app_name: Optional application name for auto-created conversations
            user_id: Optional user ID for the conversation
            auto_list_processing: Whether to automatically process list parameters (default: True)
                When True, if a function expecting a single value receives a list, the framework will
                automatically call the function for each element in the list and combine the results.
            parallel_list_processing: Whether to process list parameters in parallel (default: False)
                When True, list items are processed concurrently using a thread pool, which can
                significantly improve performance for I/O-bound operations or operations with
                substantial processing time.

        Returns:
            If return_metadata is True:
                A dictionary containing the answer and metadata about the execution,
                including session_id and auto_created flag if a conversation was created
            Otherwise:
                The result of executing the function composition, optionally enhanced with natural language

        Note:
            When session_id is None, a new conversation will be automatically created.
            The created session_id will be included in the returned metadata.
            For follow-up queries, pass the session_id from the previous response.

        Example:
            ```python
            # Sequential processing (default)
            response = nl_composer.execute_from_nl("Get details for all electronics products")

            # Parallel processing for better performance
            response = nl_composer.execute_from_nl(
                "Get details for all electronics products",
                parallel_list_processing=True
            )
            ```
        """
        # Reset token counter
        start_time = time.time()
        token_counter.reset()
        metadata = {
            "tokens_consumed": {"input": 0, "output": 0},
            "latency_taken": 0,
            "prompt_for_composition": "",
            "composition": "",
            "raw_results": {},  # Will store function-specific results
            "tool_execution_times": {},  # Will store execution times for each tool
            "prompt_for_enhanced_response": "",
            "composition_generation_latency": 0,  # Will be set by decorator
            "enhanced_response_latency": 0,  # Will be set by decorator
            "error": None,
        }

        # Store the original session_id (to track if it was auto-created)
        was_auto_created = False

        # Auto-create conversation if none provided and the composer has a conversation manager
        if session_id is None and hasattr(self.composer, "conversation_manager"):
            # Use the provided app_name or default to the composer's app_name
            current_app_name = app_name or self.composer.app_name
            session_id = self.composer.start_conversation(app_name=current_app_name, user_id=user_id)
            logger.info(f"[CONVERSATION] Automatically created new conversation with ID: {session_id}")
            was_auto_created = True

        # Always include session_id in metadata if it exists
        if session_id:
            metadata["session_id"] = session_id
            if was_auto_created:
                metadata["auto_created"] = True

        # If we're awaiting parameters, treat this as a follow-up
        if self.conversation_state["awaiting_params"]:
            follow_up_result = self.handle_follow_up(user_query)

            if not return_metadata:
                return follow_up_result

            # Return metadata with follow-up result
            end_time = time.time()
            metadata["answer"] = follow_up_result
            metadata["tokens_consumed"] = token_counter.get_total_usage()
            metadata["latency_taken"] = round(end_time - start_time, 2)
            return metadata

        variables = variables or {}

        # Store the query
        self.conversation_state["last_query"] = user_query

        try:
            # Check if we have conversation context to include
            context = ""
            if session_id and hasattr(self.composer, "conversation_manager"):
                context = self.composer.conversation_manager.get_context(session_id)
                if context:
                    metadata["has_conversation_context"] = True
                    logger.info("[CONTEXT LOG] Retrieved conversation context for ID " + str(session_id) + ":")
                    logger.info("[CONTEXT LOG] Context length: " + str(len(context)) + " characters")
                    logger.info("[CONTEXT LOG] Context first 100 chars: " + context[:100] + "...")

            # Generate the function composition with context
            if context:
                # Use context-enhanced prompt
                logger.info("[CONTEXT LOG] Using context-enhanced prompt for composition")
                metadata["prompt_for_composition"] = self.create_instruction_prompt_with_context(user_query, context)

                try:
                    composition = self.generate_composition_with_context(user_query, context, metadata=metadata)
                except Exception as e:
                    logger.error(f"[ERROR] Failed to generate composition with context: {str(e)}")
                    composition = "Error in composition"

                logger.info(
                    f"[API] Composition generation latency: {metadata['composition_generation_latency']} seconds"
                )
            else:
                # Use standard prompt
                logger.info("[CONTEXT LOG] No context available, using standard prompt")
                metadata["prompt_for_composition"] = self.create_instruction_prompt(user_query)

                try:
                    composition = self.generate_composition(user_query, metadata=metadata)
                except Exception as e:
                    logger.error(f"[ERROR] Failed to generate composition: {str(e)}")
                    composition = "Error in composition"

                logger.info(
                    f"[API] Composition generation latency: {metadata['composition_generation_latency']} seconds"
                )

            # Simplify the composition if it contains + operators
            if isinstance(composition, str) and "+" in composition:
                original_composition = composition
                composition = self._simplify_composition(composition)
                if composition != original_composition:
                    logger.info(
                        "[COMPOSITION SIMPLIFIER] Successfully simplified from: "
                        f"\n{original_composition}\nTo:\n{composition}"
                    )
                else:
                    logger.info("[COMPOSITION SIMPLIFIER] No changes made after simplification attempt")
            else:
                is_string = isinstance(composition, str)
                contains_plus = "+" in composition if is_string else False
                logger.info(
                    "[COMPOSITION SIMPLIFIER] Skipping simplification. "
                    f"Is string: {is_string}, Contains +: {contains_plus}"
                )

            metadata["composition"] = composition

            # Log the composition safely
            if isinstance(composition, dict):
                logger.info("Generated composition: " + json.dumps(composition))
            else:
                logger.info("Generated composition: " + str(composition))

            # Handle special cases (needs_info, errors, etc.)
            if isinstance(composition, dict) and composition.get("needs_info"):
                # Handle dictionary-formatted needs_info responses
                logger.info("\n=== EXECUTION PLAN SKIPPED ===")
                logger.info("Reason: Missing information")
                logger.info("Details: " + json.dumps(composition))
                logger.info("=== EXECUTION PLAN SKIPPED ===\n")

                # Try to validate and improve the needs_info response
                logger.info("[VALIDATOR] Attempting to validate dictionary needs_info response")
                improved_composition = self._validate_and_improve_composition(user_query, composition)

                # If we got back a string that's different, it was improved
                if isinstance(improved_composition, str):
                    logger.info("[VALIDATOR] Composition improved by validator: " + improved_composition)
                    composition = improved_composition
                    # Skip the error flow and continue with execution
                    metadata["composition"] = composition
                    logger.info("Improved composition: " + improved_composition)
                else:
                    logger.info("[VALIDATOR] No improvement found for dictionary needs_info")
                    # If no improvement, proceed with error flow
                    result = json.dumps(composition)
                    if use_enhanced_response:
                        prompt = self.create_enhanced_response_prompt(user_query, composition, context)
                        metadata["prompt_for_enhanced_response"] = prompt

                        # Generate enhanced response
                        result = self.generate_enhanced_response(user_query, composition, context, metadata=metadata)
                        logger.debug(
                            f"[API] Enhanced response generation latency "
                            f"(for error/needs_info): {metadata['enhanced_response_latency']} seconds"
                        )

                    metadata["raw_results"] = {"error": composition}
                    metadata["error"] = {"location": "composition_generation", "details": json.dumps(composition)}

                    # Save conversation history etc.
                    if session_id and hasattr(self.composer, "conversation_manager"):
                        self.composer.conversation_manager.add_message(
                            session_id=session_id,
                            content=user_query,
                            role="user",
                            llm_model=config.AZURE_OPENAI_MODEL_NAME,
                            llm_provider="AzureOpenAI",
                            latency_ms=0,
                            tokens_consumed={"input": 0, "output": 0},
                            functions_executed=[],
                        )

                        # Add the system response with error
                        self.composer.conversation_manager.add_message(
                            session_id=session_id,
                            content=result,
                            role="system",
                            llm_model=config.AZURE_OPENAI_MODEL_NAME,
                            llm_provider="AzureOpenAI",
                            latency_ms=int((time.time() - start_time) * 1000),
                            tokens_consumed=token_counter.get_total_usage(),
                            functions_executed=[],
                        )

                    if not return_metadata:
                        return result

                    # Return metadata with result
                    end_time = time.time()
                    metadata["answer"] = result
                    metadata["tokens_consumed"] = token_counter.get_total_usage()
                    metadata["latency_taken"] = round(end_time - start_time, 2)
                    return metadata
            elif isinstance(composition, str):
                if "needs_info" in composition or composition.startswith("Error:"):
                    logger.info("\n=== EXECUTION PLAN SKIPPED ===")
                    logger.info(
                        "Reason: " + ("Missing information" if "needs_info" in composition else "Error in composition")
                    )
                    logger.info("Details: " + composition)
                    logger.info("=== EXECUTION PLAN SKIPPED ===\n")

                    # Check if this is a needs_info response and try to validate/improve it
                    if "needs_info" in composition:
                        # Try to parse the needs_info string into a structured format
                        try:
                            # Simplified parsing for needs_info string format
                            match = re.search(r"needs_info: \[(.*?)\]", composition)
                            if match:
                                needed_info = match.group(1)
                                # Create a structured needs_info response for validation
                                needs_info_obj = {"needs_info": True, "needed": [needed_info], "context": composition}

                                # Try to validate and improve
                                logger.info("[VALIDATOR] Attempting to validate string needs_info response")
                                improved_composition = self._validate_and_improve_composition(
                                    user_query, needs_info_obj
                                )

                                # If we got back a string that's different, it was improved
                                if isinstance(improved_composition, str) and improved_composition != composition:
                                    logger.info("[VALIDATOR] Composition improved by validator")
                                    composition = improved_composition
                                    # Skip the error flow and continue with execution
                                    metadata["composition"] = composition
                                    logger.info("Improved composition: " + composition)
                                else:
                                    logger.info("[VALIDATOR] No improvement found")
                            else:
                                # Try parsing as JSON string
                                try:
                                    json_obj = json.loads(composition)
                                    if isinstance(json_obj, dict) and json_obj.get("needs_info"):
                                        logger.info("[VALIDATOR] Found JSON-formatted needs_info in string")
                                        # Run validation
                                        improved_composition = self._validate_and_improve_composition(
                                            user_query, json_obj
                                        )

                                        # If we got back a string that's different, it was improved
                                        if isinstance(improved_composition, str):
                                            logger.info("[VALIDATOR] Composition improved by validator")
                                            composition = improved_composition
                                            # Skip the error flow and continue with execution
                                            metadata["composition"] = composition
                                            logger.info("Improved composition: " + composition)
                                except json.JSONDecodeError:
                                    logger.info("[VALIDATOR] Could not parse needs_info as JSON")
                        except Exception as e:
                            logger.info("[VALIDATOR] Error parsing needs_info response: " + str(e))

                    # If we still have a needs_info response after validation, proceed with error flow
                    if "needs_info" in composition or composition.startswith("Error:"):
                        result = composition
                        if use_enhanced_response:
                            prompt = self.create_enhanced_response_prompt(user_query, composition, context)
                            metadata["prompt_for_enhanced_response"] = prompt

                            # Generate enhanced response
                            result = self.generate_enhanced_response(
                                user_query, composition, context, metadata=metadata
                            )
                            logger.debug(
                                f"[API] Enhanced response generation latency "
                                f"(for error): {metadata['enhanced_response_latency']} seconds"
                            )

                        metadata["raw_results"] = {"error": result}
                        metadata["error"] = {"location": "composition_generation", "details": json.dumps(composition)}

                        # If we have a session_id, add the user message
                        if session_id and hasattr(self.composer, "conversation_manager"):
                            self.composer.conversation_manager.add_message(
                                session_id=session_id,
                                content=user_query,
                                role="user",
                                llm_model=config.AZURE_OPENAI_MODEL_NAME,
                                llm_provider="AzureOpenAI",
                                latency_ms=0,
                                tokens_consumed={"input": 0, "output": 0},
                                functions_executed=[],
                            )

                            # Add the system response with error
                            self.composer.conversation_manager.add_message(
                                session_id=session_id,
                                content=result,
                                role="system",
                                llm_model=config.AZURE_OPENAI_MODEL_NAME,
                                llm_provider="AzureOpenAI",
                                latency_ms=int((time.time() - start_time) * 1000),
                                tokens_consumed=token_counter.get_total_usage(),
                                functions_executed=[],
                            )

                        if not return_metadata:
                            return result

                        # Return metadata with result
                        end_time = time.time()
                        metadata["answer"] = result
                        metadata["tokens_consumed"] = token_counter.get_total_usage()
                        metadata["latency_taken"] = round(end_time - start_time, 2)
                        return metadata

            # Extract function names from the composition
            function_pattern = r"([a-zA-Z_][a-zA-Z0-9_]*)\s*\("
            function_names = re.findall(function_pattern, composition)

            # If we have a session_id, add the user message before execution
            if session_id and hasattr(self.composer, "conversation_manager"):
                self.composer.conversation_manager.add_message(
                    session_id=session_id,
                    content=user_query,
                    role="user",
                    llm_model=config.AZURE_OPENAI_MODEL_NAME,
                    llm_provider="AzureOpenAI",
                    latency_ms=0,
                    tokens_consumed={"input": 0, "output": 0},
                    functions_executed=[],
                )

            # Track functions that were executed for conversation history
            functions_executed = {"composition": composition, "functions": []}

            # Extract parameters for each function call
            for func_name in function_names:
                # Match the entire function call including nested calls
                func_pattern = rf"{func_name}\(((?:[^()]|\([^()]*\))*)\)"
                func_match = re.search(func_pattern, composition)
                if func_match:
                    param_str = func_match.group(1)
                    params = {}

                    # Split parameters by comma, but preserve nested function calls
                    param_parts = []
                    current_part = ""
                    paren_count = 0

                    for char in param_str:
                        if char == "(" and '"' not in current_part:
                            paren_count += 1
                        elif char == ")" and '"' not in current_part:
                            paren_count -= 1
                        elif char == "," and paren_count == 0:
                            param_parts.append(current_part.strip())
                            current_part = ""
                            continue
                        current_part += char
                    if current_part:
                        param_parts.append(current_part.strip())

                    # Process each parameter
                    for i, part in enumerate(param_parts):
                        part = part.strip()
                        if "=" in part:
                            key, value = part.split("=", 1)
                            key = key.strip()
                            value = value.strip(" \"'")
                            params[key] = value
                        else:
                            # For positional parameters, try to get the parameter name from function signature
                            try:
                                func = self.composer.registry.get_function(func_name)
                                sig = inspect.signature(func)
                                param_names = list(sig.parameters.keys())
                                if i < len(param_names):
                                    params[param_names[i]] = part.strip(" \"'")
                                else:
                                    params[f"param_{i}"] = part.strip(" \"'")
                            except Exception:
                                # If we can't get the parameter name, use a generic one
                                params[f"param_{i}"] = part.strip(" \"'")

                    # Add this function's execution details
                    functions_executed["functions"].append(
                        {
                            "name": func_name,
                            "params": params,
                            "result": None,  # Will be updated after execution
                        }
                    )

            # Execute the composition using the execution planner
            try:
                result = self.composer.execute(
                    composition,
                    variables=variables,
                    auto_list_processing=auto_list_processing,
                    parallel_list_processing=parallel_list_processing,
                )

                # Capture tool execution times if available
                if hasattr(self.composer, "get_execution_times"):
                    metadata["tool_execution_times"] = self.composer.get_execution_times()

                # Check if the result is a structured validation error or needs_info response
                if isinstance(result, dict):
                    # Handle needs_info response in JSON format
                    if result.get("needs_info"):
                        logger.debug("[VALIDATOR] Detected needs_info in JSON format")

                        # Try to validate and improve the composition
                        improved_composition = self._validate_and_improve_composition(user_query, result)

                        # If validation returned a string (improved composition), use it
                        if isinstance(improved_composition, str) and improved_composition != result:
                            logger.debug(f"[VALIDATOR] Composition improved: {improved_composition}")
                            # Re-execute with the improved composition
                            metadata["composition"] = improved_composition
                            try:
                                result = self.composer.execute(
                                    improved_composition,
                                    variables=variables,
                                    auto_list_processing=auto_list_processing,
                                    parallel_list_processing=parallel_list_processing,
                                )
                            except Exception as e:
                                # If the improved composition fails, revert to the needs_info response
                                logger.debug(f"[VALIDATOR] Improved composition failed: {str(e)}")
                                result = deepcopy(result)
                        else:
                            logger.debug("[VALIDATOR] No improvement found for needs_info response")

                    # Handle standard error responses
                    if "error" in result:
                        # Get the error message directly from the result
                        error_message = result.get("error_message", str(result))
                        function_name = result.get("function_name", "unknown")
                        error_details = result.get("details", str(result))

                        logger.debug(f"Error in function {function_name}: {error_message}")

                        # Use the error message directly
                        user_error = f"Error: {error_message}"

                        # Set up metadata for the error
                        raw_results = {
                            "error": result.get("error"),
                            "error_message": error_message,
                            "function_name": function_name,
                        }
                        metadata["error"] = {
                            "location": "execution",
                            "message": error_message,
                            "function_name": function_name,
                            "details": error_details,
                        }

                        # Generate enhanced response for validation error immediately
                        if use_enhanced_response:
                            if context:
                                logger.debug("[CONTEXT LOG] Using context for enhanced error response")
                            prompt = self.create_enhanced_response_prompt(user_query, user_error, context)
                            metadata["prompt_for_enhanced_response"] = prompt

                            # Generate enhanced response for error
                            enhanced_error_result = self.generate_enhanced_response(
                                user_query, user_error, context, metadata=metadata
                            )
                            logger.debug(
                                f"[API] Enhanced response generation latency "
                                f"(for error): {metadata['enhanced_response_latency']} seconds",
                            )

                            # Record only the enhanced error response in the conversation history
                            if session_id and hasattr(self.composer, "conversation_manager"):
                                # Calculate metrics
                                end_time = time.time()
                                latency_ms = int((end_time - start_time) * 1000)
                                tokens_consumed = token_counter.get_total_usage()

                                # Add the enhanced error response with metrics
                                self.composer.conversation_manager.add_message(
                                    session_id=session_id,
                                    content=enhanced_error_result,
                                    role="system",
                                    llm_model=config.AZURE_OPENAI_MODEL_NAME,
                                    llm_provider="AzureOpenAI",
                                    latency_ms=latency_ms,
                                    tokens_consumed=tokens_consumed,
                                    functions_executed=functions_executed,
                                )

                            if not return_metadata:
                                return enhanced_error_result

                            metadata["answer"] = enhanced_error_result

                        # Update metadata with timing and token information
                        end_time = time.time()
                        metadata["tokens_consumed"] = token_counter.get_total_usage()
                        metadata["latency_taken"] = round(end_time - start_time, 2)

                        return metadata

                # Continue with normal result handling for non-error cases...
                # Check if the executor has tracked function outputs
                function_outputs = {}
                if hasattr(self.composer, "executor") and hasattr(self.composer.executor, "get_function_outputs"):
                    function_outputs = self.composer.executor.get_function_outputs()

                # For combined operations, handle results differently based on the result type
                raw_results = {}
                # First, check if we have tracked function outputs from the executor
                if function_outputs:
                    # Process function outputs where each function key contains a list of results
                    # with simplified parameters
                    raw_results = {}

                    for func_name, results_list in function_outputs.items():
                        if func_name in function_names:
                            # This is a function mentioned in our composition
                            if isinstance(results_list, list) and len(results_list) > 0:
                                # For multiple calls to the same function, collect all results
                                # without parameter matching
                                # Track results matched to specific function calls
                                matching_results = []

                                # Go through each function call in our execution plan
                                for func_data in functions_executed["functions"]:
                                    if func_data["name"] == func_name:
                                        # Count how many times this function appears before this instance
                                        func_index = 0
                                        for prev_func in functions_executed["functions"]:
                                            if prev_func["name"] == func_name and prev_func != func_data:
                                                func_index += 1

                                        # Use the index if it's valid, otherwise use the first result
                                        result_index = min(func_index, len(results_list) - 1)
                                        result_to_use = results_list[result_index]

                                        # Store the result in the function execution data
                                        if isinstance(result_to_use, dict) and "result" in result_to_use:
                                            func_data["result"] = result_to_use["result"]
                                            matching_results.append(result_to_use)
                                        else:
                                            func_data["result"] = result_to_use
                                            matching_results.append({"result": result_to_use})

                                # After finding matches, update raw_results
                                if matching_results:
                                    # If only one result, store it directly
                                    if len(matching_results) == 1:
                                        raw_results[func_name] = matching_results[0].get("result", matching_results[0])
                                    # If multiple results, store them as a list
                                    else:
                                        raw_results[func_name] = [item.get("result", item) for item in matching_results]

                                    logger.debug(
                                        f"[DEBUG] Updated raw_results for {func_name} with "
                                        f"{len(matching_results)} matching results"
                                    )
                            else:
                                # Single result or non-list format (backward compatibility)
                                if isinstance(results_list, dict) and "result" in results_list:
                                    raw_results[func_name] = results_list["result"]
                                else:
                                    raw_results[func_name] = results_list

                                # Update function results in the conversation history
                                for func_data in functions_executed["functions"]:
                                    if func_data["name"] == func_name:
                                        if isinstance(results_list, dict) and "result" in results_list:
                                            func_data["result"] = results_list["result"]
                                        else:
                                            func_data["result"] = results_list
                # After we've processed all function outputs,
                # check if raw_results is empty but function_outputs has data
                if not raw_results and function_outputs:
                    # Fallback: Directly use function_outputs as raw_results
                    logger.debug("No raw_results were generated. Using function_outputs directly.")
                    raw_results = function_outputs.copy()

                    # Ensure results are properly reflected in functions_executed
                    for func_data in functions_executed["functions"]:
                        func_name = func_data["name"]
                        if func_name in function_outputs:
                            # Handle both list and non-list results
                            func_output = function_outputs[func_name]

                            # If it's a list with multiple results, use position-based matching
                            if isinstance(func_output, list) and len(func_output) > 0:
                                # Count how many times this function appears before this instance
                                func_index = 0
                                for prev_func in functions_executed["functions"]:
                                    if prev_func["name"] == func_name and prev_func != func_data:
                                        func_index += 1

                                # Use the index if it's valid, otherwise use the first result
                                result_index = min(func_index, len(func_output) - 1)
                                result_to_use = func_output[result_index]

                                if isinstance(result_to_use, dict) and "result" in result_to_use:
                                    func_data["result"] = result_to_use["result"]
                                else:
                                    func_data["result"] = result_to_use
                            else:
                                # Single result
                                if isinstance(func_output, dict) and "result" in func_output:
                                    func_data["result"] = func_output["result"]
                                else:
                                    func_data["result"] = func_output
            except Exception as e:
                # Improved error handling for execution errors

                error_details = traceback.format_exc()
                error_message = str(e)
                logger.error(f"Error executing function: {error_message}")
                logger.error(error_details)

                # Create standardized error format
                user_error = f"Error: {error_message}"
                result = {
                    "error": "execution_failed",
                    "error_message": error_message,
                    "function_name": (
                        functions_executed.get("functions", [{}])[0].get("name", "unknown")
                        if functions_executed.get("functions")
                        else "unknown"
                    ),
                    "details": error_details,
                }
                raw_results = result
                metadata["error"] = {
                    "location": "execution",
                    "message": error_message,
                    "details": error_details,
                    "function_name": result["function_name"],
                }

                # Record the error in the conversation history
                if session_id and hasattr(self.composer, "conversation_manager"):
                    error_functions_executed = deepcopy(functions_executed)
                    self.composer.conversation_manager.add_message(
                        session_id=session_id,
                        content=user_error,
                        role="system",
                        llm_model=config.AZURE_OPENAI_MODEL_NAME,
                        llm_provider="AzureOpenAI",
                        latency_ms=int((time.time() - start_time) * 1000),
                        tokens_consumed=token_counter.get_total_usage(),
                        functions_executed=error_functions_executed,
                    )

                # Still pass to enhanced response generator to make it more user-friendly
                if use_enhanced_response:
                    prompt = self.create_enhanced_response_prompt(user_query, user_error, context)
                    metadata["prompt_for_enhanced_response"] = prompt
                    result = self.generate_enhanced_response(user_query, user_error, context, metadata=metadata)

            # Ensure raw_results is stored in metadata
            metadata["raw_results"] = raw_results

            # Generate enhanced response if requested (for successful executions)
            if use_enhanced_response:
                logger.debug("[DEBUG] Starting enhanced response generation")
                if context:
                    logger.debug("[CONTEXT LOG] Using context for enhanced response")
                prompt = self.create_enhanced_response_prompt(user_query, result, context)
                metadata["prompt_for_enhanced_response"] = prompt

                # Safe transformation of results to prevent errors
                logger.debug(
                    f"[DEBUG] About to call generate_enhanced_response with raw_result: " f"{str(raw_results)[:100]}..."
                )

                # Generate enhanced response
                try:
                    enhanced_result = self.generate_enhanced_response(
                        user_query, raw_results, context, metadata=metadata
                    )
                    logger.debug(
                        f"[API] Enhanced response generation latency: "
                        f"{metadata['enhanced_response_latency']} seconds"
                    )
                    logger.debug(f"[DEBUG] Generated enhanced response: {enhanced_result[:100]}...")

                    # Use the enhanced result instead of the raw result
                    result_to_use = enhanced_result
                except Exception as e:
                    error_trace = traceback.format_exc()
                    logger.debug(f"[ERROR] Failed to generate enhanced response: {str(e)}")
                    logger.debug(f"[ERROR] Traceback: {error_trace}")
                    # Fall back to original result
                    result_to_use = str(result)
            else:
                logger.debug("[DEBUG] Enhanced response generation skipped (use_enhanced_response=False)")
                # If enhanced response not requested, use the raw result
                result_to_use = result

            # Record the response in the conversation history
            if session_id and hasattr(self.composer, "conversation_manager"):
                # Calculate metrics
                end_time = time.time()
                latency_ms = int((end_time - start_time) * 1000)
                tokens_consumed = token_counter.get_total_usage()

                # Add the system response with enhanced metrics
                self.composer.conversation_manager.add_message(
                    session_id=session_id,
                    content=str(result),  # Use enhanced result when available
                    role="system",
                    llm_model=config.AZURE_OPENAI_MODEL_NAME,
                    llm_provider="AzureOpenAI",
                    latency_ms=latency_ms,
                    tokens_consumed=tokens_consumed,
                    functions_executed=functions_executed,
                )

            if not return_metadata:
                return result_to_use

            metadata["answer"] = result_to_use

            # Update metadata with timing and token information
            end_time = time.time()
            metadata["tokens_consumed"] = token_counter.get_total_usage()
            metadata["latency_taken"] = round(end_time - start_time, 2)

            return metadata

        except Exception as e:
            error_details = traceback.format_exc()
            logger.error(f"Error executing natural language query: {e}\n{error_details}")

            error_message = f"Error: {str(e)}"

            # Record the error in the conversation history
            if session_id and hasattr(self.composer, "conversation_manager"):
                # Add the error message with metrics
                error_functions_executed = {
                    "composition": (composition if isinstance(composition, str) else "Error in composition"),
                    "functions": [],
                }

                self.composer.conversation_manager.add_message(
                    session_id=session_id,
                    content=error_message,
                    role="system",
                    llm_model=config.AZURE_OPENAI_MODEL_NAME,
                    llm_provider="AzureOpenAI",
                    latency_ms=int((time.time() - start_time) * 1000),
                    tokens_consumed=token_counter.get_total_usage(),
                    functions_executed=error_functions_executed,
                )

            if not return_metadata:
                return error_message

            metadata["error"] = {"message": str(e), "details": error_details}
            metadata["answer"] = error_message

            end_time = time.time()
            metadata["tokens_consumed"] = token_counter.get_total_usage()
            metadata["latency_taken"] = round(end_time - start_time, 2)

            return metadata

    def _standardize_results(self, raw_result):
        """Standardize results into a consistent string format.

        Args:
            raw_result: The raw result from executing functions (any type)

        Returns:
            str: Formatted result as a string
        """
        # For errors, just return as is
        if isinstance(raw_result, str) and (raw_result.startswith("Error:") or "needs_info" in raw_result):
            return raw_result

        # Handle error objects (dictionaries with an 'error' key)
        if isinstance(raw_result, dict) and "error" in raw_result:
            error_message = raw_result.get("error_message", raw_result.get("error", "An error occurred"))
            return f"Error: {error_message}"

        # Handle combined results from "+" operators that return a dictionary with the combined format
        if isinstance(raw_result, dict) and "combined" in raw_result and "individual_results" in raw_result:
            return raw_result["combined"]

        # Handle pipe-separated multi-function results
        if isinstance(raw_result, str) and "|" in raw_result:
            sections = raw_result.split("|")
            formatted_sections = []
            for section in sections:
                try:
                    # Try to parse as JSON
                    parsed = json.loads(section.strip())
                    formatted_sections.append(self.format_enhanced_response(parsed))
                except json.JSONDecodeError:
                    # If not valid JSON, use as is
                    formatted_sections.append(section.strip())

            return " | ".join(formatted_sections)

        # Use the existing format_enhanced_response for other types
        return self.format_enhanced_response(raw_result)

    def _get_function_docstrings(self):
        """Extract and format docstrings from available functions.

        Returns:
            str: Formatted docstrings from available functions
        """
        if not hasattr(self, "composer") or not self.composer:
            return "No functions available."

        # The FunctionComposer has 'registry' attribute, not 'function_registry'
        if hasattr(self.composer, "registry"):
            function_registry = self.composer.registry.functions
        else:
            return "No functions available."

        formatted_docstrings = []

        for function_name, function_obj in function_registry.items():
            if function_obj and hasattr(function_obj, "__doc__") and function_obj.__doc__:
                # Clean and format the docstring
                docstring = function_obj.__doc__.strip()
                # Limit docstring length if too long
                if len(docstring) > 500:
                    docstring = docstring[:497] + "..."
                formatted_docstrings.append(f"Function: {function_name}\nDescription: {docstring}\n")
            else:
                # Fallback if no docstring
                formatted_docstrings.append(f"Function: {function_name}\nDescription: No description available\n")

        return "\n".join(formatted_docstrings)

    def create_enhanced_response_prompt(self, user_query, raw_result, conversation_context=None):
        """Create the prompt for enhanced response generation.

        This method extracts the prompt creation logic from generate_enhanced_response
        to make it available for metadata tracking.

        Args:
            user_query: The original natural language query
            raw_result: The raw result from executing the function composition
            conversation_context: Optional context from previous conversation turns

        Returns:
            str: The prompt for enhanced response generation
        """
        # Convert all results to standardized string format
        formatted_result = self._standardize_results(raw_result)

        # Base prompt with role definition
        prompt = "You are an AI assistant that provides natural conversational responses based on function results.\n\n"

        # Add function docstrings for context
        if hasattr(self, "composer") and self.composer:
            function_docstrings = self._get_function_docstrings()
            prompt += "FUNCTIONS OVERVIEW:\n" + function_docstrings + "\n\n"

        # Add conversation context if available
        if conversation_context:
            logger.info("[CONTEXT LOG] Adding conversation context to enhanced response prompt")
            logger.info(
                "[CONTEXT LOG] Context length in response prompt: " + str(len(conversation_context)) + " characters"
            )
            prompt += "CONVERSATION CONTEXT:\n" + conversation_context + "\n\n"

        # Add query and result data
        prompt += f"""Query: "{user_query}"
Result Data: {formatted_result}

CURRENT QUERY AND RESULT - RESPOND DIRECTLY TO THIS:
User Asked: "{user_query}"
Current Result: {formatted_result}

CRITICAL GUIDELINES FOR RESPONSES:

1. CORE PRINCIPLES:
   - ONLY use information from the Result Data in your response
   - NEVER suggest or imply capabilities that aren't explicitly defined in the Functions Overview
   - NEVER offer to help with services that aren't available in the registered functions
   - When a capability doesn't exist, be direct and clear about the limitation

2. HANDLING LIMITATIONS:
   - When the user requests something you cannot do:
     ✓ Clearly state that you cannot perform that specific action
     ✓ DO NOT suggest alternatives that aren't in your function set
     ✓ DO NOT ask follow-up questions about tasks you cannot perform
     ✓ DO NOT imply you might be able to help with it later
   - Use phrases like:
     ✓ "I apologize, but I cannot [specific request]. This functionality is not available."
     ✓ "I'm not able to help with [specific request]."
   - AVOID phrases like:
     × "Let me help you find alternatives..."
     × "Would you like me to suggest other options?"
     × "I could assist you with..."

3. SUCCESSFUL RESPONSES:
   - Present the result clearly and naturally
   - Use conversational language and friendly tone
   - Focus only on what was accomplished
   - DO NOT add caveats about other capabilities

4. ERROR HANDLING:
   - Be polite and apologetic when errors occur
   - Explain the issue in simple terms
   - DO NOT suggest workarounds that aren't supported by available functions
   - DO NOT offer to help with related tasks unless explicitly supported

5. MISSING PARAMETERS:
   - Only ask for additional information if the function exists and just needs more parameters
   - Be specific about what information is needed
   - DO NOT ask for information for functions that don't exist

6. TONE AND STYLE:
   - Always be polite and professional
   - Use natural, conversational language
   - Maintain a helpful attitude while staying within your capabilities
   - Be direct and honest about limitations

Remember: Your primary goal is to provide accurate, helpful responses while being absolutely clear about
          what you can and cannot do based on the available functions."""

        return prompt

    @measure_execution_time(log_prefix="Enhanced response generation", metadata_key="enhanced_response_latency")
    def generate_enhanced_response(self, user_query, raw_result, conversation_context=None, metadata=None):
        """Generate an enhanced natural language response.

        This takes the original query and the raw function results and
        asks the LLM to create a more natural, contextual response.

        Args:
            user_query: The original natural language query
            raw_result: The raw result from executing the function composition
            conversation_context: Optional context from previous conversation turns
            metadata: Optional dictionary to store timing information

        Returns:
            str: An enhanced natural language response
        """
        logger.info("[ENHANCED RESPONSE] Generating enhanced response for query: " + user_query[:50] + "...")
        logger.info("[ENHANCED RESPONSE] Raw result to enhance: " + str(raw_result)[:100] + "...")

        try:
            prompt = self.create_enhanced_response_prompt(user_query, raw_result, conversation_context)
            logger.info("[ENHANCED RESPONSE] Created prompt of length: " + str(len(prompt)))

            # Base system message
            base_system_message = """You are a friendly, helpful assistant. Your goal is to
            provide responses that sound like they come from a human assistant, not a computer.
            Always respond conversationally as if you're having a friendly chat with the user.
            Never output raw data - always transform it into natural, flowing sentences a helpful person would say.
            Use a warm, helpful tone throughout your response, and humanize technical details.
            When formulating your response, include citations from relevant documents in the [docX] format,
            where X represents the document's sequential order (e.g., [doc1], [doc2], [doc3]).
            If multiple documents are referenced, ensure all applicable citations are included, not just [doc1]."""

            # Apply custom response guidelines if available
            if self.custom_response_guidelines:
                system_message = f"{base_system_message}\n\n{self.custom_response_guidelines}"
                logger.debug("[ENHANCED RESPONSE] Using custom response guidelines")
            else:
                system_message = base_system_message

            logger.debug("[DEBUG] Calling call_llm for enhanced response")
            response = get_openai_response(prompt, system_message=system_message, json_mode=True)
            logger.debug(f"[DEBUG] call_llm returned: {str(response)[:100]}...")

            # Check for errors in the response
            if "error" in response:
                logger.error("[ENHANCED RESPONSE ERROR] OpenAI API error: " + response["error"])
                # Fall back to the raw result to avoid returning an error message
                logger.info("[ENHANCED RESPONSE] Falling back to raw result")
                return str(raw_result)

            enhanced_response = response.get("response", "")
            if not enhanced_response:
                logger.error("Empty response from OpenAI API")
                enhanced_response = str(raw_result)

            logger.info(
                "[ENHANCED RESPONSE] Successfully generated enhanced response: " + enhanced_response[:100] + "..."
            )

            # Add a basic validation to ensure we got a meaningful response
            if len(enhanced_response) < 10 or enhanced_response == "Error communicating with AI service":
                logger.warning("[ENHANCED RESPONSE WARNING] Generated response looks problematic: " + enhanced_response)
                # Fall back to the raw result
                return str(raw_result)

            # Log the complete enhanced response
            logger.info("\n[FINAL ENHANCED RESPONSE]")
            logger.info("-" * 40)
            logger.info(enhanced_response)
            logger.info("-" * 40 + "\n")

            return enhanced_response

        except Exception as e:
            # Log the error and stack trace
            error_details = traceback.format_exc()
            logger.error(f"[ENHANCED RESPONSE ERROR] Failed to generate enhanced response: {str(e)}")
            logger.error(f"[ENHANCED RESPONSE ERROR] Stack trace: {error_details}")
            logger.error(f"[ERROR] Exception in generate_enhanced_response: {str(e)}")
            logger.error(f"[ERROR] Traceback: {error_details}")

            # Fall back to using the raw result
            return str(raw_result)

    def _safely_serialize_result(self, result):
        """Safely serialize any result type for inclusion in metadata.

        This method ensures that any result type can be safely stored
        in the metadata object regardless of its original type.

        Args:
            result: Any result object

        Returns:
            A JSON-serializable representation of the result
        """
        # Handle common simple types
        if result is None or isinstance(result, (str, int, float, bool)):
            return result

        # Handle dictionaries (recursively serialize values)
        if isinstance(result, dict):
            return {k: self._safely_serialize_result(v) for k, v in result.items()}

        # Handle lists (recursively serialize items)
        if isinstance(result, list):
            return [self._safely_serialize_result(item) for item in result]

        # For other types, convert to string
        try:
            # Try JSON serialization first
            return json.loads(json.dumps(result, default=str))
        except (TypeError, json.JSONDecodeError):
            # Fall back to string representation
            return str(result)

    def format_enhanced_response(self, result):
        """Format result data into a more readable string.

        Args:
            result: Raw result data (dictionaries, lists, etc.)

        Returns:
            Formatted string representation of the result
        """
        # Handle error objects
        if isinstance(result, dict) and "error" in result:
            error_message = result.get("error_message", "An error occurred")
            return f"Error: {error_message}"

        if isinstance(result, dict):
            # Format dictionary in a more readable way
            formatted = []
            for key, value in result.items():
                # Recursively format nested structures
                if isinstance(value, (dict, list)):
                    value = self.format_enhanced_response(value)
                # Format key-value pairs
                formatted.append(f"{key.replace('_', ' ').title()}: {value}")
            return "\n".join(formatted)

        elif isinstance(result, list):
            # Format list items
            formatted = []
            for item in result:
                # Recursively format nested structures
                if isinstance(item, (dict, list)):
                    formatted.append(self.format_enhanced_response(item))
                else:
                    formatted.append(f"- {item}")
            return "\n".join(formatted)

        else:
            # Return simple values as strings
            return str(result)

    def create_instruction_prompt_with_context(self, user_query, conversation_context):
        """Create a prompt that includes conversation context from previous turns."""
        logger.info("[CONTEXT LOG] Creating instruction prompt with context")
        logger.info(f"[CONTEXT LOG] Context in instruction prompt: {len(conversation_context)} characters")

        registered_functions = self.get_function_descriptions()

        prompt = f"""You are a Function Composition Expert who takes natural language queries and
        converts them to function compositions.

CONVERSATION CONTEXT:
{conversation_context}

USER'S CURRENT QUERY:
{user_query}

AVAILABLE FUNCTIONS:
{registered_functions}

FUNCTION COMPOSITION TASK:
1. Analyze the user's query and the conversation context
2. Determine which function(s) need to be called based on both the query and relevant context
3. Check if the user's query is a follow-up that relies on context from the conversation
4. Return a valid function composition to execute

RULES:
- MUST return a valid Python expression not a python code block
- Do not add any type conversions like str()
- MUST only use the available functions
- If the user's query is a follow-up question, use the conversation context to resolve references
- If multiple functions need to be executed, combine them with the + operator
- If information is missing and cannot be inferred from context, return "needs_info: [what's missing]"
- If you can't determine the functions to call, return "Error: [explanation]"

Your response must be ONLY the Python function composition, nothing else.
Examples:
1. "What's the weather in New York?" => get_weather("New York", "today")
2. "How far is it from Los Angeles to San Francisco?" => calculate_distance("Los Angeles", "San Francisco")
3. "What's the weather in Chicago and how far is it from New York?"
    => get_weather("Chicago", "today") + calculate_distance("Chicago", "New York")
4. "How's the weather there?" (with context mentioning Paris) => get_weather("Paris", "today")

DO NOT include python code block dont include ```python or use str or anything like that. Just give function expression
example:
dont return write_email("gayathri@gmail.com", "Weather Forecast for London",
"Hi GG, Here is the weather forecast for the next 5 days in London: " + str(get_forecast("London", 5)))
instead return:
write_email("gayathri@gmail.com", "Weather Forecast for London",
"Hi GG, Here is the weather forecast for the next 5 days in London: " + get_forecast("London", 5))

Return your answer:
"""
        return prompt

    @measure_execution_time(log_prefix="Composition generation", metadata_key="composition_generation_latency")
    def generate_composition_with_context(self, user_query, conversation_context, metadata=None):
        """Generate a function composition expression from natural language with context.

        Args:
            user_query: The natural language query from the user
            conversation_context: The conversation context
            metadata: Optional dictionary to store timing information

        Returns:
            str: A function composition expression
        """
        prompt = self.create_instruction_prompt_with_context(user_query, conversation_context)

        # Add system message to ensure proper formatting
        system_message = """You are a function composition expert. Your task is to convert natural language to
        function calls.

EXTREMELY IMPORTANT: Return ONLY the raw function call as plain text without any code block formatting,
markdown syntax, or ```python prefix.

For example, return:
check_resort_availability("Sun Beach Resort", "April 1st")

NOT:
```python
check_resort_availability("Sun Beach Resort", "April 1st")
```

DO NOT wrap your response in any code block or add any explanation. Return ONLY the function call."""

        response = get_openai_response(prompt, system_message=system_message, json_mode=False)

        # Handle both string and dictionary responses
        if isinstance(response, dict):
            composition = response.get("response", "").strip()
        else:
            composition = str(response).strip()

        # Remove any code block formatting if it still exists
        if composition.startswith("```") and composition.endswith("```"):
            composition = re.sub(r"^```(?:python)?\s*|\s*```$", "", composition)

        return composition

    def _enhance_with_context(self, query, context):
        """Enhance a query with conversation context.

        Args:
            query: The original query
            context: The conversation context

        Returns:
            str: The enhanced query with context
        """
        prompt = f"""Given a conversation context and a new user query, rewrite the query to be self-contained
and include all relevant information from the context needed to answer it properly.

CONVERSATION CONTEXT:
{context}

NEW USER QUERY:
{query}

REWRITTEN QUERY:
"""

        response = get_openai_response(prompt, json_mode=False)
        enhanced_query = response.get("response", "").strip()

        # If something went wrong, fall back to the original query
        if not enhanced_query:
            return query

        return enhanced_query

    def _get_available_services(self):
        """Get a string description of available services based on registered functions"""
        if not hasattr(self, "composer") or not self.composer:
            return ""

        functions = self.composer.get_registered_functions()
        if not functions:
            return ""

        # Get function names
        function_names = list(functions.keys())

        # Format the list of available services
        if len(function_names) <= 3:
            return ", ".join(function_names)
        else:
            # For too many functions, list a few with "and more"
            return f"{', '.join(function_names[:3])}, and others"

    def _get_available_functions_description(self):
        """Get a description of the available functions in the current application.

        Returns:
            str: A formatted description of available functions
        """
        if not hasattr(self, "composer") or not self.composer:
            return "No functions available."

        functions = self.get_function_descriptions()
        if not functions:
            return "No functions are available in this application."

        return functions

    def _simplify_composition(self, composition):
        """Simplify a composition by removing unnecessary steps in function chains.

        This method analyzes compositions with multiple function calls connected by '+'
        operators and identifies if they represent a progression of steps where only the
        final result is needed, rather than a collection of independent results.

        Args:
            composition: The original function composition as a string

        Returns:
            str: The simplified composition
        """
        # Only process compositions with + operators
        if "+" not in composition:
            logger.info("[COMPOSITION SIMPLIFIER] No + operator found in composition")
            return composition

        logger.info("[COMPOSITION SIMPLIFIER] Starting simplification for composition: " + composition)

        prompt = f"""
        Analyze this function composition and determine if it can be simplified:

        Original composition: {composition}

        RULES:
        1. If the composition contains intermediate results that are just steps toward a final result,
           eliminate the intermediate steps and keep only the final computation.

        2. If the composition contains truly independent operations that should return separate results
           (like getting information for multiple items), keep these separate operations with the + operator.

        3. DO NOT modify the actual function call parameters or change their order.

        EXAMPLES:

        Invalid composition (should simplify):
        getProfileData("user123") + analyzeUserActivity(getProfileData("user123")) +
        generateRecommendations(analyzeUserActivity(getProfileData("user123")))
        Simplified to:
        generateRecommendations(analyzeUserActivity(getProfileData("user123")))

        Another invalid example:
        fetchData("source1") + processData(fetchData("source1")) +
        visualizeData(processData(fetchData("source1")))
        Simplified to:
        visualizeData(processData(fetchData("source1")))

        Valid composition (keep as is):
        getCityInfo("Boston") + getCityInfo("Chicago")
        This is already correct as it requests two independent results.

        Valid composition (keep as is):
        translateText("Hello", "Spanish") + translateText("Goodbye", "Spanish")
        This is already correct as it requests two independent translations.

        Return a JSON object with the following format:
        {{
            "simplified": true or false,
            "expression": "simplified_expression_here_if_simplifiable_otherwise_original"
        }}
        """

        logger.info("[COMPOSITION SIMPLIFIER] Sending prompt to LLM for simplification")
        response = get_openai_response(
            prompt,
            system_message=(
                "You are a function simplification expert. Return a JSON object with "
                "'simplified' (boolean) and 'expression' (string) fields."
            ),
            json_mode=True,
        )

        logger.info("[COMPOSITION SIMPLIFIER] LLM response: " + json.dumps(response))

        # Extract the simplified expression from the JSON response
        if "simplified" in response and "expression" in response:
            is_simplified = response.get("simplified", False)
            simplified_expr = response.get("expression", "").strip()

            if is_simplified and simplified_expr and simplified_expr != composition:
                logger.info("[COMPOSITION SIMPLIFIER] Composition can be simplified: " + simplified_expr)

                # Validate the simplified composition
                try:
                    ast.parse(simplified_expr)
                    logger.info(
                        "[COMPOSITION SIMPLIFIER] Successfully validated simplified composition: " + simplified_expr
                    )
                    return simplified_expr
                except SyntaxError as e:
                    logger.error("[COMPOSITION SIMPLIFIER] Simplified composition has syntax error: " + str(e))
                    return composition
            else:
                logger.info("[COMPOSITION SIMPLIFIER] No simplification needed according to LLM")
                return composition
        else:
            # If there was an error with the JSON response, return the original composition
            logger.error("[COMPOSITION SIMPLIFIER] Error in LLM response, returning original composition")
            return composition

    def match_function_results(self, function_name, function_params, results_list):
        """Match function calls to results with improved reliability.

        This method implements a multi-strategy approach to result matching:
        1. First tries normalized parameter matching (case-insensitive, type-tolerant)
        2. Falls back to timestamp ordering if available
        3. Uses positional matching as last resort

        Args:
            function_name: Name of the function that was called
            function_params: Parameters passed to the function
            results_list: List of results for this function

        Returns:
            dict: The best matching result or None if no match found
        """
        if not results_list:
            return None

        # Strategy 1: Normalized parameter matching
        best_match = None
        best_match_score = 0

        # If we only have one result, use it directly
        if len(results_list) == 1:
            return results_list[0]

        for result_item in results_list:
            if not isinstance(result_item, dict) or "params_summary" not in result_item:
                continue

            params_summary = result_item.get("params_summary", {})

            # Calculate match score using normalized comparison
            match_score = 0
            total_params = 0

            for param_key, param_value in function_params.items():
                total_params += 1

                if param_key not in params_summary:
                    continue

                # Get parameter values
                call_value = param_value
                result_value = params_summary[param_key]

                # Normalize both values for comparison
                call_norm = str(call_value).lower().strip()
                result_norm = str(result_value).lower().strip()

                # Exact match after normalization
                if call_norm == result_norm:
                    match_score += 1
                # Partial match (one contains the other)
                elif call_norm in result_norm or result_norm in call_norm:
                    match_score += 0.5

            # Calculate final match score percentage
            if total_params > 0:
                match_percentage = match_score / total_params

                # Update best match if we found a better one
                if match_percentage > best_match_score:
                    best_match_score = match_percentage
                    best_match = result_item

                    # If we have a perfect match, stop searching
                    if match_percentage == 1.0:
                        return best_match

        # If we found a reasonable match (at least 50% parameters match)
        if best_match_score >= 0.5:
            return best_match

        # Strategy 2: Sort by timestamp and use latest result
        try:
            timestamp_results = [r for r in results_list if isinstance(r, dict) and r.get("timestamp")]
            if timestamp_results:
                latest_result = sorted(timestamp_results, key=lambda x: x.get("timestamp", 0), reverse=True)[0]
                return latest_result
        except Exception:
            pass

        # Strategy 3: Just return the first result as fallback
        return results_list[0]
