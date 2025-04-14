"""
Core Function Composition Framework

A lightweight framework for composing functions with specific input/output signatures.
"""

import ast
import re
import time
import json
import hashlib
import inspect
import traceback
import networkx as nx
from enum import Enum
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Tuple, Set, Optional
from agentic_inventory.utils.extensions import logger
from agentic_inventory.framework.core.conversation_manager import ConversationManager
from agentic_inventory.framework.utils.performance_metrics import (
    measure_execution_time,
    get_performance_metrics,
    reset_performance_metrics,
)


class ExecutionType(Enum):
    PARALLEL = "parallel"
    SEQUENTIAL = "sequential"


@dataclass
class FunctionNode:
    """Represents a function in the execution plan"""

    name: str
    params: Dict[str, Any]
    dependencies: Set[str]  # Names of functions this depends on
    provides: Set[str]  # Output parameters this function provides
    execution_type: ExecutionType = ExecutionType.SEQUENTIAL
    start_time: float = 0.0
    end_time: float = 0.0
    registry: Any = None  # Reference to the function registry for dependency resolution
    runtime_dependencies: Set[str] = field(default_factory=set)  # Runtime dependencies from registry

    @property
    def execution_time(self) -> float:
        """Get the execution time of this function in seconds"""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return 0.0

    @measure_execution_time(log_prefix="Function node execution")
    def execute(self, **kwargs):
        """Execute this function node and track performance."""
        if not self.registry:
            raise ValueError("Cannot execute function node without registry")

        function = self.registry.get_function(self.name)
        # Record start time
        self.start_time = time.perf_counter()
        result = function(**{**self.params, **kwargs})
        # Record end time
        self.end_time = time.perf_counter()
        return result


class ExecutionPlan:
    """Represents the execution plan for a set of functions"""

    def __init__(self):
        self.nodes: List[FunctionNode] = []
        self.parallel_groups: List[List[FunctionNode]] = []
        self.sequential_nodes: List[FunctionNode] = []
        self.parallel_execution_time: float = 0.0
        self.sequential_execution_time: float = 0.0

    def add_node(self, node: FunctionNode):
        self.nodes.append(node)

    def detect_cycles(self):
        """Detect cycles in the dependency graph using NetworkX.

        Returns:
            List of cycles found in the dependency graph, or empty list if no cycles exist

        A cycle is a list of function names that form a circular dependency chain.
        """
        # Create a dependency graph using NetworkX
        G = nx.DiGraph()

        # Add nodes and edges to the graph with CORRECT direction
        # If B depends on A, add edge A → B (meaning A must be executed before B)
        for node in self.nodes:
            # Use unique name if available
            node_name = getattr(node, "unique_name", node.name)

            # Add the node to the graph
            G.add_node(node_name)

            # Combine explicit and runtime dependencies
            all_deps = node.dependencies.union(node.runtime_dependencies)

            # Add edges FROM dependencies TO the dependent node
            for dep in all_deps:
                # Add edge FROM dependency TO dependent
                G.add_edge(dep, node_name)

        # Find all cycles in the graph
        cycles = []

        # Check for direct self-dependencies first
        for node_name in G.nodes():
            if G.has_edge(node_name, node_name):
                cycles.append([node_name, node_name])

        # Use NetworkX to find more complex cycles
        try:
            # Get all simple cycles in the graph
            graph_cycles = list(nx.simple_cycles(G))

            # Process cycles for better readability
            for cycle in graph_cycles:
                # Skip cycles that are direct self-dependencies (already handled)
                if len(cycle) == 1:
                    continue

                # Add the first element also at the end to make the cycle more obvious
                full_cycle = cycle + [cycle[0]]
                cycles.append(full_cycle)
        except nx.NetworkXNoCycle:
            logger.debug("Execution Plan - No cycles detected by NetworkX")
        except Exception as e:
            logger.error(f"Execution Plan - Error in cycle detection: {str(e)}", exc_info=True)

        return cycles

    def calculate_execution_stats(self):
        """Calculate execution statistics"""
        # Initialize values to avoid errors
        self.parallel_execution_time = 0.0
        self.sequential_execution_time = 0.0
        theoretical_sequential_time = 0.0

        # Check if there are actually any nodes with valid execution times
        has_timing_data = any(
            node.start_time > 0 and node.end_time > 0 for group in self.parallel_groups for node in group
        )
        has_timing_data = has_timing_data or any(
            node.start_time > 0 and node.end_time > 0 for node in self.sequential_nodes
        )

        if has_timing_data:
            # Calculate total parallel and sequential times
            self.parallel_execution_time = sum(
                max([node.execution_time for node in group] or [0]) for group in self.parallel_groups
            )

            self.sequential_execution_time = sum(node.execution_time for node in self.sequential_nodes)

            # Calculate theoretical sequential time (if everything ran sequentially)
            theoretical_sequential_time = (
                sum(sum(node.execution_time for node in group) for group in self.parallel_groups)
                + self.sequential_execution_time
            )

        # Calculate speedup if possible
        speedup = 0
        if (self.parallel_execution_time + self.sequential_execution_time) > 0:
            speedup = theoretical_sequential_time / (self.parallel_execution_time + self.sequential_execution_time)

        return {
            "parallel_time": self.parallel_execution_time,
            "sequential_time": self.sequential_execution_time,
            "total_time": self.parallel_execution_time + self.sequential_execution_time,
            "theoretical_sequential_time": theoretical_sequential_time,
            "speedup": speedup,
            "has_timing_data": has_timing_data,
        }

    def get_performance_report(self):
        """Generate a detailed performance report for this execution plan."""
        metrics = {
            "parallel_groups": len(self.parallel_groups),
            "sequential_nodes": len(self.sequential_nodes),
            "total_nodes": len(self.nodes),
            "execution_times": {node.name: node.execution_time for node in self.nodes if node.execution_time > 0},
            "parallel_execution_time": self.parallel_execution_time,
            "sequential_execution_time": self.sequential_execution_time,
            "total_execution_time": self.parallel_execution_time + self.sequential_execution_time,
        }

        # Add execution plan statistics
        stats = self.calculate_execution_stats()
        metrics.update(stats)

        return metrics

    def visualize(self) -> str:
        """Generate a visual representation of the execution plan.

        Returns:
            str: A string representation of the execution plan with ASCII art
        """

        # Helper function for formatting parameters consistently
        def format_params(node_params):
            param_list = []
            for param_name, param_value in node_params.items():
                # Skip internal parameters that start with underscore
                if param_name.startswith("_"):
                    continue
                # Format the parameter value based on its type
                if isinstance(param_value, str):
                    param_list.append(f"{param_name}='{param_value}'")
                elif isinstance(param_value, (int, float, bool, type(None))):
                    param_list.append(f"{param_name}={param_value}")
                elif isinstance(param_value, list):
                    # For lists of simple values, show them all
                    formatted_values = []
                    for val in param_value:
                        if isinstance(val, str):
                            formatted_values.append(f"'{val}'")
                        elif isinstance(val, (int, float, bool, type(None))):
                            formatted_values.append(str(val))
                        else:
                            formatted_values.append("...")
                    param_list.append(f"{param_name}=[{', '.join(formatted_values)}]")
                else:
                    # For complex types, just show the type
                    param_list.append(f"{param_name}=...")
            return param_list

        output = ["EXECUTION PLAN VISUALIZATION\n"]

        # Show all nodes and their dependencies
        output.append("📋 REGISTERED FUNCTIONS AND DEPENDENCIES:")

        # Track unique function identifiers for distinguishing parallel calls
        unique_id_map = {}

        for i, node in enumerate(self.nodes):
            # Create a unique identifier for each function instance based on parameters
            # Use a more stable approach to distinguish different calls to the same function
            param_digest = str(sorted([(k, str(v)[:20]) for k, v in node.params.items()]))
            unique_id = f"{node.name}_{i}_{hash(param_digest) & 0xffffffff:08x}"
            unique_id_map[id(node)] = unique_id

            # Get all dependencies - combine AST-derived and runtime dependencies
            ast_deps = set(node.dependencies) - node.runtime_dependencies
            runtime_deps = node.runtime_dependencies if hasattr(node, "runtime_dependencies") else set()

            # Format parameters
            param_list = format_params(node.params)

            # Join parameters with commas for display
            key_param = ", ".join(param_list) if param_list else ""

            # Format display name with parameter identifier
            display_name = f"{node.name}" if not key_param else f"{node.name}({key_param})"

            # Show dependencies in a tree-like structure
            output.append(f"  • {display_name} (Type: {node.execution_type.value})")
            output.append(f"    ├─ AST Dependencies: {', '.join(ast_deps) if ast_deps else 'none'}")

            if runtime_deps:
                output.append(f"    ├─ Runtime Dependencies: {', '.join(runtime_deps)}")
            else:
                output.append("    ├─ Runtime Dependencies: none")

            output.append(f"    └─ Parameters: {node.params}")
            output.append("")

        # Create a graph showing execution order
        output.append("\n🔀 COMPLETE DEPENDENCY GRAPH:")
        output.append("⬇️ EXECUTION ORDER (from top to bottom)\n")

        # Group parallel and sequential nodes for visualization
        all_groups = []

        # Start with parallel groups
        for i, group in enumerate(self.parallel_groups, 1):
            output.append(f"── Parallel Group {i} ──")
            for node in group:
                # Format parameters
                param_list = format_params(node.params)

                # Join parameters with commas for display
                node_key_param = ", ".join(param_list) if param_list else ""

                deps_str = ""
                if hasattr(node, "runtime_dependencies") and node.runtime_dependencies:
                    deps_str = f" ⟵ Runtime deps: {', '.join(node.runtime_dependencies)}"
                output.append(f"│ ⇶ {node.name}({node_key_param}){deps_str}")
            output.append("──" + "─" * 50 + "──")
            all_groups.append(("parallel", i, group))

        # Add sequential nodes
        for i, node in enumerate(self.sequential_nodes, 1):
            output.append(f"── Sequential Node {i} ──")

            # Format parameters
            param_list = format_params(node.params)

            # Join parameters with commas for display
            node_key_param = ", ".join(param_list) if param_list else ""

            deps_str = ""
            if hasattr(node, "runtime_dependencies") and node.runtime_dependencies:
                deps_str = f" ⟵ Runtime deps: {', '.join(node.runtime_dependencies)}"
            output.append(f"│ → {node.name}({node_key_param}){deps_str}")
            output.append("──" + "─" * 50 + "──")
            all_groups.append(("sequential", i, [node]))

        # Show parallel groups separately for clarity
        output.append("\n🔄 PARALLEL EXECUTION GROUPS:")
        for i, group in enumerate(self.parallel_groups, 1):
            output.append(f"  Group {i}:")
            for node in group:
                # Format parameters
                param_list = format_params(node.params)

                # Join parameters with commas for display
                node_key_param = ", ".join(param_list) if param_list else ""

                output.append(f"    ⇶ {node.name}({node_key_param})")
            output.append("")

        # Show sequential nodes
        if self.sequential_nodes:
            output.append("\n⏩ SEQUENTIAL EXECUTION CHAIN:")
            for i, node in enumerate(self.sequential_nodes, 1):
                # Format parameters
                param_list = format_params(node.params)

                # Join parameters with commas for display
                node_key_param = ", ".join(param_list) if param_list else ""

                output.append(f"  {i}. → {node.name}({node_key_param})")
            output.append("")

        # Create a timeline visualization
        output.append("\n⏱️ EXECUTION FLOW DIAGRAM:")
        output.append("TIME ─" + "─" * 50 + "▶\n")

        # Show each execution group
        for group_type, group_id, group in all_groups:
            if group_type == "parallel":
                output.append(f"Group {group_id}: │" + "─" * 25 + "│")
                for node in group:
                    # Format parameters
                    param_list = format_params(node.params)

                    # Join parameters with commas for display
                    node_key_param = ", ".join(param_list) if param_list else ""

                    output.append(f"         │ {node.name}({node_key_param}) │")
            else:
                output.append(f"Node {group_id}:  │" + "─" * 15 + "│")
                node = group[0]

                # Format parameters
                param_list = format_params(node.params)

                # Join parameters with commas for display
                node_key_param = ", ".join(param_list) if param_list else ""

                output.append(f"         │ {node.name}({node_key_param}) │")
            output.append("")

        output.append("\n📊 PARALLEL EXECUTION METRICS")

        # Generate a simplified timeline visualization
        output.append("\n📈 Detailed Timeline:")
        output.append("No execution timing information available (run execute() to get timing data).")

        return "\n".join(output)

    @measure_execution_time(log_prefix="Dependency analysis")
    def analyze_dependencies(self):
        """Analyze the dependencies between nodes and set up the execution order.

        This method analyzes the dependencies between nodes and sets up the execution
        order. It also checks for circular dependencies.

        Returns:
            ExecutionPlan: The execution plan with dependencies analyzed

        Raises:
            ValueError: If circular dependencies are detected
        """
        # Check for circular dependencies first
        cycles = self.detect_cycles()
        if cycles:
            # Format the cycles for better readability
            cycle_paths = []
            for cycle in cycles:
                cycle_str = " -> ".join(cycle)
                cycle_paths.append(cycle_str)

            error_message = "Circular dependencies detected in execution plan:\n"
            error_message += "\n".join(cycle_paths)
            raise ValueError(error_message)

        # Continue with topological sorting if no cycles exist
        G = nx.DiGraph()

        # Create a mapping of node names to nodes
        node_map = {}
        for node in self.nodes:
            node_name = getattr(node, "unique_name", node.name)
            node_map[node_name] = node
            G.add_node(node_name)

        # Add edges based on dependencies
        for node in self.nodes:
            node_name = getattr(node, "unique_name", node.name)
            # Use both explicit and runtime dependencies
            all_deps = node.dependencies.union(node.runtime_dependencies)
            for dep in all_deps:
                # Add edge FROM dependency TO dependent
                G.add_edge(dep, node_name)

        # Reset execution levels
        self.parallel_groups = []
        self.sequential_nodes = []

        # STEP 1: First, handle nodes explicitly marked for parallel execution (e.g., from "+" operations)
        parallel_marked_nodes = [node for node in self.nodes if node.execution_type == ExecutionType.PARALLEL]
        if parallel_marked_nodes:
            logger.debug(f"Found {len(parallel_marked_nodes)} nodes marked for parallel execution")
            # Add these nodes as a single parallel group
            self._add_to_parallel(parallel_marked_nodes)

            # Remove these nodes from further analysis
            processed_node_names = {getattr(node, "unique_name", node.name) for node in parallel_marked_nodes}
        else:
            processed_node_names = set()

        # STEP 2: Process remaining nodes with topological sorting
        try:
            # Get all connected components
            components = list(nx.weakly_connected_components(G))

            for component in components:
                # Skip nodes we've already processed
                component = {node for node in component if node not in processed_node_names}
                if not component:
                    continue

                # Create a subgraph for this component
                subgraph = G.subgraph(component)

                # Check if it's a single node with no dependencies
                if len(subgraph.nodes) == 1 and len(subgraph.edges) == 0:
                    node_name = list(subgraph.nodes)[0]
                    # Add to parallel group (no dependencies)
                    if node_name in node_map and node_name not in processed_node_names:
                        self._add_to_parallel([node_map[node_name]])
                        processed_node_names.add(node_name)
                else:
                    # Perform topological sort on the subgraph
                    for level, node_group in enumerate(nx.topological_generations(subgraph)):
                        # Filter out already processed nodes
                        node_group = {node for node in node_group if node not in processed_node_names}
                        if not node_group:
                            continue

                        if len(node_group) > 1:
                            # If multiple nodes at this level, they can be executed in parallel
                            nodes = [node_map[name] for name in node_group if name in node_map]
                            if nodes:
                                self.parallel_groups.append(nodes)
                                processed_node_names.update(node_group)
                        else:
                            # Single node, add to sequential chain
                            node_name = list(node_group)[0]
                            if node_name in node_map and node_name not in processed_node_names:
                                self.sequential_nodes.append(node_map[node_name])
                                processed_node_names.add(node_name)

            return self
        except nx.NetworkXUnfeasible:
            # This should never happen as we've already checked for cycles
            raise ValueError("Circular dependencies detected in execution plan.")
        except Exception as e:
            raise ValueError(f"Error analyzing dependencies: {str(e)}")

    def _add_to_parallel(self, nodes):
        """Add nodes to parallel execution groups."""
        if nodes:
            self.parallel_groups.append(nodes)

    def _add_parallel_group(self, node_names):
        """Add a group of nodes to parallel execution groups."""
        # Create a mapping of node names to nodes
        node_map = {}
        for node in self.nodes:
            node_name = getattr(node, "unique_name", node.name)
            node_map[node_name] = node

        # Get the actual nodes from the names
        nodes = [node_map[name] for name in node_names if name in node_map]
        if nodes:
            self.parallel_groups.append(nodes)

    def _add_to_sequential(self, node_name):
        """Add a node to sequential execution chain."""
        # Create a mapping of node names to nodes
        node_map = {}
        for node in self.nodes:
            node_name_key = getattr(node, "unique_name", node.name)
            node_map[node_name_key] = node

        # Get the actual node from the name
        if node_name in node_map:
            self.sequential_nodes.append(node_map[node_name])


class ExecutionPlanner:
    """Analyzes function composition expressions and creates execution plans."""

    def __init__(self, registry: "FunctionRegistry"):
        """Initialize with a function registry.

        Args:
            registry: The function registry containing the available functions
        """
        self.registry = registry
        self.current_function_name = None  # For tracking recursive dependencies

    @measure_execution_time(log_prefix="Expression analysis")
    def analyze_expression(self, expression: str) -> ExecutionPlan:
        """Analyze a function composition expression and create an execution plan

        Args:
            expression: The function composition expression from LLM

        Returns:
            ExecutionPlan: The analyzed execution plan
        """
        plan = ExecutionPlan()

        # Check for "+" operator to detect potential parallel execution
        if "+" in expression and " + " in expression:
            logger.debug("DEBUG - Detected '+' operator in expression, will analyze for parallel execution")
            parts = expression.split(" + ")

            # For each part, parse it as a separate function call
            for part in parts:
                part = part.strip()
                try:
                    # Parse the part
                    part_tree = ast.parse(part)

                    # Extract function call from part
                    for node in ast.walk(part_tree):
                        if isinstance(node, ast.Call):
                            function_name = self._get_function_name(node)
                            self.current_function_name = function_name
                            params = self._extract_parameters(node)
                            dependencies = self._analyze_dependencies(node)
                            provides = self._analyze_output(function_name)

                            # Create FunctionNode with registry reference and set to PARALLEL execution type
                            function_node = FunctionNode(
                                name=function_name,
                                params=params,
                                dependencies=dependencies,
                                provides=provides,
                                registry=self.registry,
                                execution_type=ExecutionType.PARALLEL,  # Set as parallel execution
                            )

                            plan.add_node(function_node)
                            self.current_function_name = None
                            break  # Only process the top-level function call in each part
                except SyntaxError:
                    logger.debug(f"DEBUG - Syntax error parsing part: {part}")
                    continue
                except Exception as e:
                    logger.debug(f"DEBUG - Error parsing part {part}: {str(e)}")
                    continue
        else:
            # Original parsing for non-"+" expressions
            try:
                tree = ast.parse(expression)
            except SyntaxError:
                raise ValueError(f"Invalid expression syntax: {expression}")

            # Walk the AST to find function calls and their dependencies
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    function_name = self._get_function_name(node)
                    self.current_function_name = function_name  # Set current function name
                    params = self._extract_parameters(node)
                    dependencies = self._analyze_dependencies(node)
                    provides = self._analyze_output(function_name)

                    # Create FunctionNode with registry reference
                    function_node = FunctionNode(
                        name=function_name,
                        params=params,
                        dependencies=dependencies,
                        provides=provides,
                        registry=self.registry,  # Pass registry for runtime dependency tracking
                    )

                    plan.add_node(function_node)
                    self.current_function_name = None  # Reset current function name

        # Analyze dependencies and create execution groups
        plan.analyze_dependencies()
        return plan

    def _get_function_name(self, node: ast.Call) -> str:
        """Extract function name from AST node"""
        if isinstance(node.func, ast.Name):
            return node.func.id
        elif isinstance(node.func, ast.Attribute):
            return node.func.attr
        raise ValueError(f"Unsupported function call type: {type(node.func)}")

    def _extract_parameters(self, node: ast.Call) -> Dict[str, Any]:
        """Extract parameters from function call with improved natural language mapping.

        Args:
            node: AST Call node representing a function call

        Returns:
            Dictionary of parameter names and values
        """
        params = {}

        # Get function signature to understand expected parameters
        function_name = self._get_function_name(node)
        try:
            func = self.registry.get_function(function_name)
            sig = inspect.signature(func)
            param_names = list(sig.parameters.keys())

            # Process positional arguments with parameter names
            for i, arg in enumerate(node.args):
                if i < len(param_names):
                    # Map position to parameter name
                    param_name = param_names[i]
                    if isinstance(arg, ast.Constant):
                        params[param_name] = arg.value
                    elif isinstance(arg, ast.Name):
                        params[param_name] = arg.id
                    elif isinstance(arg, ast.Call):
                        # Handle nested function calls
                        params[param_name] = f"_func_{self._get_function_name(arg)}"
                else:
                    # Fallback for extra positional args
                    if isinstance(arg, ast.Constant):
                        params[f"arg_{i}"] = arg.value
                    elif isinstance(arg, ast.Name):
                        params[f"arg_{i}"] = arg.id
                    elif isinstance(arg, ast.Call):
                        params[f"arg_{i}"] = f"_func_{self._get_function_name(arg)}"

            # Process keyword arguments
            for keyword in node.keywords:
                if isinstance(keyword.value, ast.Constant):
                    params[keyword.arg] = keyword.value.value
                elif isinstance(keyword.value, ast.Name):
                    params[keyword.arg] = keyword.value.id
                elif isinstance(keyword.value, ast.Call):
                    # Handle nested function calls
                    params[keyword.arg] = f"_func_{self._get_function_name(keyword.value)}"
        except Exception as e:
            logger.error(f"Error mapping parameters for {function_name}: {e}", exc_info=True)
            # Fallback to basic extraction
            # Fallback to basic extraction
            for i, arg in enumerate(node.args):
                if isinstance(arg, ast.Constant):
                    params[f"arg_{i}"] = arg.value
                elif isinstance(arg, ast.Name):
                    params[f"arg_{i}"] = arg.id
                elif isinstance(arg, ast.Call):
                    params[f"arg_{i}"] = f"_func_{self._get_function_name(arg)}"

            for keyword in node.keywords:
                if isinstance(keyword.value, ast.Constant):
                    params[keyword.arg] = keyword.value.value
                elif isinstance(keyword.value, ast.Name):
                    params[keyword.arg] = keyword.value.id
                elif isinstance(keyword.value, ast.Call):
                    params[keyword.arg] = f"_func_{self._get_function_name(keyword.value)}"

        return params

    def _analyze_dependencies(self, node: ast.Call) -> Set[str]:
        """Analyze function dependencies by looking at nested calls"""
        dependencies = set()

        for child in ast.walk(node):
            if isinstance(child, ast.Call) and child != node:
                dependencies.add(self._get_function_name(child))

        return dependencies

    def _analyze_output(self, function_name: str) -> Set[str]:
        """Analyze what parameters a function provides as output"""
        # For now, we'll use a simple approach - just mark the function name as output
        # This could be enhanced to analyze actual return types and structures
        return {function_name}


class FunctionRegistry:
    """Registry for functions with their signatures and documentation."""

    def __init__(self):
        """Initialize an empty registry."""
        self.functions = {}
        self.dependencies = {}  # Store function dependencies
        self.signatures: Dict[str, Tuple[List[str], Any]] = {}

    def check_circular_dependencies(self, func_name: str, new_dependencies: List[Dict] = None) -> List[List[str]]:
        """Check if adding new dependencies would create circular dependencies using NetworkX.

        Args:
            func_name: The function name being registered
            new_dependencies: List of new dependency configurations

        Returns:
            List of circular dependency chains if circular dependencies are detected, empty list otherwise
        """
        if not new_dependencies:
            return []

        # Extract the function names of the new dependencies
        new_dep_functions = [dep.get("function") for dep in new_dependencies if dep.get("function")]

        # Create a directed graph using NetworkX
        G = nx.DiGraph()

        # Add existing dependencies with CORRECT direction
        # If B depends on A, add edge A → B (meaning A must be executed before B)
        for dependent, deps in self.dependencies.items():
            dep_funcs = [dep.get("function") for dep in deps if dep.get("function")]
            for dependency in dep_funcs:
                # Add edge FROM dependency TO dependent
                G.add_edge(dependency, dependent)

        # Add the potential new dependencies with CORRECT direction
        for dependency in new_dep_functions:
            # Check for direct self-dependency
            if dependency == func_name:
                return [[func_name, func_name]]

            # Add edge FROM dependency TO the new function
            G.add_edge(dependency, func_name)

        # Now check for cycles
        try:
            cycles = list(nx.simple_cycles(G))

            # Return only cycles that involve the new function
            result_cycles = []
            for cycle in cycles:
                if func_name in cycle:
                    # Rotate cycle to start with func_name for better readability
                    idx = cycle.index(func_name)
                    rotated_cycle = cycle[idx:] + cycle[:idx]
                    # Add func_name at the end too, to make the cycle more obvious
                    final_cycle = rotated_cycle + [rotated_cycle[0]]
                    result_cycles.append(final_cycle)

            return result_cycles
        except nx.NetworkXNoCycle:
            return []
        except Exception as e:
            logger.error(f"Error in cycle detection: {str(e)}", exc_info=True)
            return []

    def register(self, func: Callable = None, *, name: str = None, dependencies: List[Dict] = None):
        """Register a function.

        Args:
            func: The function to register
            name: Optional custom name (defaults to function name)
            dependencies: Optional list of dependencies for this function

        Returns:
            The function, allowing this to be used as a decorator

        Raises:
            ValueError: If a circular dependency is detected
        """
        dependencies = dependencies or []

        def decorator(f):
            nonlocal name
            func_name = name or f.__name__

            # Check for circular dependencies before registering
            cycles = self.check_circular_dependencies(func_name, dependencies)

            if cycles:
                cycle_paths = []
                for cycle in cycles:
                    if len(cycle) == 2 and cycle[0] == cycle[1]:
                        # Direct self-dependency
                        cycle_paths.append(f"{cycle[0]} -> self")
                    else:
                        # Indirect cycle
                        cycle_paths.append(" -> ".join(cycle))

                cycle_str = ", ".join(cycle_paths)
                error_msg = (
                    f"Circular dependencies detected: {cycle_str}. Cannot register function with circular dependencies."
                )
                logger.error(f"Function Registry - Error registering function {func_name}: {error_msg}", exc_info=True)
                raise ValueError(error_msg)

            # Store the function and its dependencies
            self.functions[func_name] = f
            self.dependencies[func_name] = dependencies

            # Store the function's signature for later use
            params = list(inspect.signature(f).parameters.keys())
            return_type = inspect.signature(f).return_annotation
            self.signatures[func_name] = (params, return_type)
            return f

        if func is None:
            return decorator
        return decorator(func)

    def get_function(self, name: str) -> Callable:
        """Get a registered function by name."""
        if name in self.functions:
            return self.functions[name]
        logger.warning(f"Function Registry - Function not found: {name}")
        raise ValueError(f"Function {name} not found in registry")

    def get_signature(self, name: str) -> Tuple[List[str], Any]:
        """Get the signature (parameters and return annotation) of a function."""
        func = self.get_function(name)
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())
        return_annotation = sig.return_annotation
        return params, return_annotation

    def get_dependencies(self, name: str) -> List[Dict]:
        """Get dependencies for a function."""
        return self.dependencies.get(name, [])


class FunctionParser:
    """Parser for function composition expressions."""

    def __init__(self, registry: FunctionRegistry):
        """Initialize with a function registry."""
        self.registry = registry

    @measure_execution_time(log_prefix="Expression parsing")
    def parse(self, expression: str) -> dict:
        """Parse an expression into a computation graph.

        Args:
            expression: A string expression to parse

        Returns:
            A dictionary representing the computation graph
        """
        try:
            logger.debug(f"\nDEBUG - Parsing expression: {expression}")
            # Check if we have a combined expression (a + b + c)
            if "+" in expression and " + " in expression:
                # Split by "+" and recursively process each part
                parts = expression.split(" + ")
                if len(parts) < 2:
                    # Fallback to regular parsing if split doesn't work as expected
                    tree = ast.parse(expression, mode="eval")
                    result = self._parse_node(tree.body)
                    logger.debug(f"DEBUG - Parse result (combined fallback): {result}")
                    return result

                # Parse the first part
                left = self.parse(parts[0].strip())

                # Combine with the rest
                right = self.parse(" + ".join(parts[1:]).strip())

                # Create an operation node
                result = {"type": "operation", "op": "add", "left": left, "right": right}
                logger.debug(f"DEBUG - Parse result (combined): {result}")
                return result
            else:
                # Regular parsing
                tree = ast.parse(expression, mode="eval")
                result = self._parse_node(tree.body)
                logger.debug(f"DEBUG - Parse result (regular): {result}")
                return result
        except SyntaxError as e:
            logger.error(f"DEBUG - SyntaxError parsing expression: {e}", exc_info=True)
            raise ValueError(f"Invalid expression syntax: {e}")
        except Exception as e:
            logger.error(f"DEBUG - Error parsing expression: {e}", exc_info=True)
            raise ValueError(f"Error parsing expression: {str(e)}")

    def _parse_node(self, node) -> dict:
        """Parse a single AST node.

        Args:
            node: An AST node

        Returns:
            A dictionary representing the node in our computation graph
        """
        # Function call: func(arg1, arg2, kwarg1=val1)
        if isinstance(node, ast.Call):
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                # Handle cases like module.function
                parts = []
                current = node.func
                while isinstance(current, ast.Attribute):
                    parts.append(current.attr)
                    current = current.value
                if isinstance(current, ast.Name):
                    parts.append(current.id)
                func_name = ".".join(reversed(parts))
            else:
                raise ValueError(f"Unsupported function reference: {ast.dump(node.func)}")

            # Check if the function exists in the registry
            if func_name not in self.registry.functions:
                raise ValueError(f"Function '{func_name}' not found in registry")

            # Parse positional arguments
            args = [self._parse_node(arg) for arg in node.args]

            # Parse keyword arguments
            kwargs = {kw.arg: self._parse_node(kw.value) for kw in node.keywords}

            return {
                "type": "function_call",
                "function": func_name,
                "args": args,
                "kwargs": kwargs,
                "params": {},  # Add empty params dict for later population
            }

        # Constant value: 42, "hello", True, None
        elif isinstance(node, ast.Constant):
            return {"type": "const", "value": node.value}

        # Variable reference: x, y, age
        elif isinstance(node, ast.Name):
            return {"type": "variable", "name": node.id}

        # Binary operations: a + b, a - b, etc.
        elif isinstance(node, ast.BinOp):
            # Handle different binary operations
            if isinstance(node.op, ast.Add):
                op = "add"
            elif isinstance(node.op, ast.Sub):
                op = "sub"
            elif isinstance(node.op, ast.Mult):
                op = "mult"
            elif isinstance(node.op, ast.Div):
                op = "div"
            else:
                raise ValueError(f"Unsupported binary operator: {type(node.op).__name__}")

            # Parse both sides of the operation
            left = self._parse_node(node.left)
            right = self._parse_node(node.right)

            return {"type": "operation", "op": op, "left": left, "right": right}

        # Lists: [a, b, c]
        elif isinstance(node, ast.List):
            elements = [self._parse_node(elt) for elt in node.elts]
            return {"type": "const", "value": elements}

        # Dictionaries: {"key": value}
        elif isinstance(node, ast.Dict):
            keys = []
            for key in node.keys:
                if key is None:
                    # Handle dict unpacking: {**other_dict}
                    raise ValueError("Dictionary unpacking is not supported")
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    raise ValueError("Dictionary keys must be string literals")
                keys.append(key.value)

            values = [self._parse_node(value) for value in node.values]

            # Create dictionary from keys and values
            result_dict = {}
            for k, v in zip(keys, values):
                if v.get("type") == "const":
                    result_dict[k] = v["value"]
                else:
                    # For non-constants, we can't evaluate them statically
                    # Just store the parsed node
                    result_dict[k] = v

            return {"type": "const", "value": result_dict}

        # Unary operations: -a, +a, not a
        elif isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                # Negative number: -42
                if isinstance(node.operand, ast.Constant) and isinstance(node.operand.value, (int, float)):
                    return {"type": "const", "value": -node.operand.value}

            # Other unary operators not yet supported
            raise ValueError(f"Unsupported unary operator: {type(node.op).__name__}")

        # Subscripts: dict["key"], list[0]
        elif isinstance(node, ast.Subscript):
            # This is a complex operation that would need to be expanded
            # For now, we'll raise an error
            raise ValueError(
                "Subscript operations (like dict['key']) are not directly supported. "
                + "Use functions to extract values from collections."
            )

        # Other node types are not supported
        else:
            raise ValueError(f"Unsupported expression node: {type(node)}")


class FunctionExecutor:
    """Executes function compositions."""

    def __init__(self, registry, parser):
        """Initialize with a registry and parser.

        Args:
            registry: FunctionRegistry instance
            parser: FunctionParser instance
        """
        self.registry = registry
        self.parser = parser
        self.function_outputs = {}
        self.function_outputs_detailed = {}  # New structure for detailed tracking with parameters
        self.execution_results = {}
        self.execution_times = {}  # Simple dictionary to track execution times

    def reset_tracking(self):
        """Reset the function output tracking."""
        self.function_outputs = {}
        self.function_outputs_detailed = {}  # Reset the detailed tracking as well
        self.execution_results = {}  # Reset execution results
        self.execution_times = {}  # Reset execution times

    def get_function_outputs(self):
        """Get the outputs from the last execution.

        Returns:
            dict: A dictionary mapping function names to their outputs
        """
        return self.function_outputs

    def get_detailed_function_outputs(self):
        """Get detailed outputs from the last execution including parameter context.

        Returns:
            dict: A dictionary mapping unique function call identifiers to detailed information
                  including function name, parameters, and results
        """
        return self.function_outputs_detailed

    def _generate_function_key(self, function_name, params):
        """Generate a unique key for a function call based on its name and parameters.

        Args:
            function_name: The name of the function
            params: Dictionary of parameters passed to the function

        Returns:
            str: A unique key for this function call
        """

        # Create a stable string representation of parameters
        # First, ensure all values are JSON serializable
        serializable_params = {}
        for k, v in params.items():
            try:
                # Try to use the value directly
                json.dumps({k: v})
                serializable_params[k] = v
            except (TypeError, OverflowError):
                # If not serializable, use string representation
                serializable_params[k] = str(v)

        # Sort keys for consistency and create parameter string
        param_str = json.dumps(serializable_params, sort_keys=True)

        # Create a hash of the parameters
        param_hash = hashlib.md5(param_str.encode()).hexdigest()[:8]

        # Return a key combining function name and parameter hash
        return f"{function_name}_{param_hash}"

    def _resolve_path(self, obj, path):
        """Resolve a path in an object, handling dictionaries, JSON strings, and objects with attributes.

        Args:
            obj: The object to resolve the path in
            path: The path to resolve (using dot notation)

        Returns:
            The value at the path or None if not found
        """
        # Handle JSON strings
        if isinstance(obj, str):
            try:
                obj = json.loads(obj)
            except json.JSONDecodeError:
                # Not a valid JSON string, can't resolve path
                return None

        # Handle None
        if obj is None:
            return None

        # Split the path
        parts = path.split(".")
        current = obj

        # Traverse the path
        for part in parts:
            # Handle dictionary access
            if isinstance(current, dict) and part in current:
                current = current[part]
            # Handle object attribute access
            elif hasattr(current, part):
                current = getattr(current, part)
            else:
                # Path doesn't exist
                return None

        return current

    def _apply_transform(self, value, transform_spec):
        """Apply a transformation to a value.

        Args:
            value: The value to transform
            transform_spec: The transformation to apply (function, type, or callable)

        Returns:
            The transformed value
        """
        if transform_spec is None:
            return value

        try:
            if isinstance(transform_spec, type):
                # Handle type conversion like str, int, float
                return transform_spec(value)
            elif callable(transform_spec):
                # Handle functions and lambdas
                return transform_spec(value)
            else:
                logger.warning(f"      ⚠️ Invalid transform specification: {transform_spec}")
                return value
        except Exception as e:
            logger.error(f"      ⚠️ Error applying transformation: {str(e)}", exc_info=True)
            return value

    @measure_execution_time(log_prefix="Function execution", metadata_key="execution_time")
    def execute(
        self,
        expression: str,
        variables: Dict[str, Any] = None,
        auto_list_processing: bool = True,
        parallel_list_processing: bool = False,
        metadata: Dict = None,
    ) -> Any:
        """Execute a function composition expression.

        This method parses and executes a function composition expression,
        replacing variable placeholders with provided values.

        Args:
            expression: The function composition expression to execute
            variables: Dictionary of variable values to use during execution
            auto_list_processing: Whether to automatically process list parameters (when a function
                                 returns a list but the next function expects a single value)
            parallel_list_processing: Whether to process list parameters in parallel (when auto_list_processing is True)
            metadata: Optional dictionary to store timing information

        Returns:
            The result of executing the expression, or an error object if execution fails
        """
        # Store these as instance attributes so they're available to _execute_node
        self.auto_list_processing = auto_list_processing
        self.parallel_list_processing = parallel_list_processing

        logger.debug(f"DEBUG - Parsing expression: {expression}")
        graph = self.parser.parse(expression)
        logger.debug(f"DEBUG - Parse result (regular): {graph}")

        if not graph:
            return {"error": "parsing_failed", "error_message": "Failed to parse expression", "function_name": "parse"}

        logger.debug(f"\nDEBUG - Parsed expression: {graph}")

        variables = variables or {}
        try:
            result = self._execute_node(graph, variables)
            return result
        except Exception as e:
            error_details = traceback.format_exc()
            logger.error(f"ERROR - Exception during execution: {error_details}", exc_info=True)
            return {"error": "execution_failed", "error_message": str(e), "function_name": "execute"}

    def _extract_functions_from_expression(self, graph):
        """Extract functions from a complex expression using simplified parsing.

        Args:
            graph: The parsed graph or a representation of the expression

        Returns:
            list: A list of function nodes
        """
        logger.debug(f"DEBUG - Extract functions from parsed data: {graph}")
        nodes = []

        # Check if we have a direct function call
        if isinstance(graph, dict) and graph.get("type") == "function_call":
            return [graph]

        # Check if we can extract from operations
        if isinstance(graph, dict) and graph.get("type") == "operation":
            # Recursively extract functions from left and right sides
            if graph.get("left"):
                if graph["left"].get("type") == "function_call":
                    nodes.append(graph["left"])
                else:
                    # Recursive extraction for nested operations
                    nodes.extend(self._extract_functions_from_expression(graph["left"]))

            if graph.get("right"):
                if graph["right"].get("type") == "function_call":
                    nodes.append(graph["right"])
                else:
                    # Recursive extraction for nested operations
                    nodes.extend(self._extract_functions_from_expression(graph["right"]))

        logger.debug(f"DEBUG - Extracted function nodes: {nodes}")
        return nodes

    @measure_execution_time(log_prefix="Node execution")
    def _execute_node(self, node: dict, variables: Dict[str, Any]) -> Any:
        """Execute a function call node with variable substitution.

        Args:
            node: Node representation from the parser
            variables: Dictionary of variable values for substitution

        Returns:
            Result of executing the function
        """
        # Handle null node
        if node is None:
            return None

        # Handle different node types
        if isinstance(node, dict) and "type" in node:
            node_type = node["type"]

            # Handle constant values
            if node_type == "const":
                return node.get("value")

            # Handle variable references
            elif node_type == "variable":
                var_name = node.get("name")
                if var_name in variables:
                    return variables[var_name]
                return f"{{${var_name}}}"  # Return template var for later substitution

            # Handle function calls - main logic
            elif node_type == "function_call":
                # 1. Extract function name
                if "function" in node:
                    function_name = node["function"]
                elif "name" in node:
                    function_name = node["name"]
                else:
                    raise ValueError("Function node must have a 'function' or 'name' field")

                logger.debug(f"DEBUG - Function name extracted: {function_name}")
                logger.debug(f"DEBUG - Looking up dependencies for {function_name}")
                dependencies = self.registry.get_dependencies(function_name)
                logger.debug(f"DEBUG - Dependencies found: {dependencies}")

                # 2. Extract and prepare parameters
                params = {}

                # 2a. Extract parameters from 'params' field
                if "params" in node and node["params"]:
                    params.update(node["params"])
                    logger.debug(f"DEBUG - Params after updating from node['params']: {params}")

                # 2b. Extract positional arguments from 'args' if present
                if "args" in node and node["args"]:
                    args = node["args"]
                    # Get function signature to map positional args to named params
                    try:
                        function_obj = self.registry.get_function(function_name)
                        sig = inspect.signature(function_obj)
                        param_names = list(sig.parameters.keys())

                        for i, arg in enumerate(args):
                            if i < len(param_names):
                                param_name = param_names[i]

                                # Handle constants
                                if arg["type"] == "const":
                                    logger.debug(
                                        f"      📄 Added parameter '{param_name}' = '{arg['value']}' from args"
                                    )
                                    params[param_name] = arg["value"]
                                # Handle function calls
                                elif arg["type"] == "function_call":
                                    # This is a nested function call - we'll handle it specially
                                    nested_func = arg.copy()  # Clone to avoid modifying the original

                                    # Execute the nested function directly with recursive call
                                    logger.debug(
                                        "      🔄 Found nested function call: "
                                        + nested_func.get("function", nested_func.get("name"))
                                        + " as parameter "
                                        + param_name
                                    )
                                    try:
                                        # Execute nested function recursively
                                        nested_result = self._execute_node(nested_func, variables)

                                        # Check if result is an error
                                        if isinstance(nested_result, dict) and "error" in nested_result:
                                            logger.error(
                                                "      ❌ Nested function execution failed: "
                                                + nested_result.get("error_message", "Unknown error")
                                            )
                                            # Add parent function context to error
                                            nested_result["parent_function"] = function_name
                                            return nested_result

                                        # Update parameter with nested function result
                                        params[param_name] = nested_result
                                        logger.debug(
                                            "      ✅ Updated parameter '"
                                            + param_name
                                            + "' with nested function result: "
                                            + str(nested_result)
                                        )
                                    except Exception as e:
                                        logger.error(
                                            f"      ❌ Error executing nested function: {str(e)}", exc_info=True
                                        )
                                        error_msg = f"Error in nested function for parameter '{param_name}': {str(e)}"
                                        return {
                                            "error": "nested_function_execution_failed",
                                            "error_message": error_msg,
                                            "function_name": nested_func.get(
                                                "function", nested_func.get("name", "unknown")
                                            ),
                                            "parent_function": function_name,
                                        }
                                # Handle variable references
                                elif arg["type"] == "variable":
                                    var_name = arg["name"]
                                    if var_name in variables:
                                        logger.debug(
                                            "      📄 Added parameter '"
                                            + param_name
                                            + "' = '"
                                            + str(variables[var_name])
                                            + "' from variable"
                                        )
                                        params[param_name] = variables[var_name]
                                    else:
                                        logger.warning(
                                            f"      ⚠️ Variable '{var_name}' referenced but not found in variables"
                                        )
                                        params[param_name] = f"{{${var_name}}}"  # Placeholder
                    except Exception as e:
                        logger.error(f"      ⚠️ Error mapping positional args to parameters: {str(e)}", exc_info=True)

                    logger.debug(f"DEBUG - Params after processing args: {params}")

                # 2c. Extract keyword arguments from 'kwargs' if present
                if "kwargs" in node and node["kwargs"]:
                    logger.debug(f"DEBUG - Processing kwargs: {node['kwargs']}")
                    for key, value in node["kwargs"].items():
                        if isinstance(value, dict) and "type" in value:
                            # Handle constants
                            if value["type"] == "const":
                                params[key] = value["value"]
                            # Handle function calls
                            elif value["type"] == "function_call":
                                # This is a nested function call - execute it directly
                                nested_func = value.copy()  # Clone to avoid modifying the original

                                logger.debug(
                                    "      🔄 Found nested function call in kwargs: "
                                    + nested_func.get("function", nested_func.get("name"))
                                    + " as parameter "
                                    + key
                                )
                                try:
                                    # Execute nested function recursively
                                    nested_result = self._execute_node(nested_func, variables)

                                    # Check if result is an error
                                    if isinstance(nested_result, dict) and "error" in nested_result:
                                        logger.error(
                                            "      ❌ Nested function execution failed: "
                                            + nested_result.get("error_message", "Unknown error")
                                        )
                                        # Add parent function context to error
                                        nested_result["parent_function"] = function_name
                                        return nested_result

                                    # Update parameter with nested function result
                                    params[key] = nested_result
                                    logger.debug(
                                        "      ✅ Updated parameter '"
                                        + key
                                        + "' with nested function result: "
                                        + str(nested_result)
                                    )
                                except Exception as e:
                                    logger.error(f"      ❌ Error executing nested function: {str(e)}", exc_info=True)
                                    # Extract nested function name from the parameter value
                                    nested_func_name = nested_func.get("function", nested_func.get("name", "unknown"))
                                    error_msg = (
                                        f"Error in nested function '{nested_func_name}' "
                                        f"for parameter '{key}': {str(e)}"
                                    )
                                    return {
                                        "error": "nested_function_execution_failed",
                                        "error_message": error_msg,
                                        "function_name": nested_func_name,
                                        "parent_function": function_name,
                                    }
                            # Handle variable references
                            elif value["type"] == "variable":
                                var_name = value["name"]
                                if var_name in variables:
                                    params[key] = variables[var_name]
                                else:
                                    params[key] = f"{{${var_name}}}"  # Placeholder
                        else:
                            params[key] = value

                    logger.debug(f"DEBUG - Params after processing kwargs: {params}")

                # 3. Process string format parameters that represent function calls
                for param_name, param_value in list(params.items()):
                    # Handle _func_ prefixed strings (legacy format)
                    if isinstance(param_value, str) and param_value.startswith("_func_"):
                        nested_func_name = param_value[6:]  # Remove '_func_' prefix
                        logger.debug(f"DEBUG - Found _func_ reference for parameter {param_name}: {nested_func_name}")

                        # Check if this is a registered function
                        if not self.registry.get_function(nested_func_name):
                            error_msg = (
                                "Function '"
                                + nested_func_name
                                + "' referenced as '"
                                + param_name
                                + "' parameter is not registered"
                            )
                            logger.error("      ❌ " + error_msg, exc_info=True)
                            return {
                                "error": "function_not_found",
                                "error_message": error_msg,
                                "function_name": function_name,
                            }

                        # Check execution results first
                        if nested_func_name in self.execution_results:
                            result = self.execution_results[nested_func_name]
                            params[param_name] = result
                            logger.debug(
                                "      ✅ Parameter '"
                                + param_name
                                + "' updated with result from previously executed function: "
                                + str(result)
                            )
                        else:
                            # Execute the function
                            try:
                                nested_func = self.registry.get_function(nested_func_name)
                                nested_result = nested_func()
                                params[param_name] = nested_result
                                # Store for future reference
                                self.execution_results[nested_func_name] = nested_result
                                logger.debug(
                                    "      ✅ Parameter '"
                                    + param_name
                                    + "' updated with result from executed function: "
                                    + str(nested_result)
                                )
                            except Exception as e:
                                logger.error(
                                    "      ❌ Error executing function '" + nested_func_name + "': " + str(e),
                                    exc_info=True,
                                )
                                error_msg = (
                                    "      ❌ Error executing function '"
                                    + nested_func_name
                                    + "' for parameter '"
                                    + param_name
                                    + "': "
                                    + str(e)
                                )
                                return {
                                    "error": "function_execution_failed",
                                    "error_message": error_msg,
                                    "function_name": nested_func_name,
                                    "parent_function": function_name,
                                }

                    # Handle parameters that are dictionaries with name and params (direct nested functions)
                    elif isinstance(param_value, dict) and "name" in param_value and "params" in param_value:
                        nested_func_dict = param_value
                        nested_func_name = nested_func_dict["name"]
                        logger.debug(
                            f"DEBUG - Found nested function dict for parameter {param_name}: {nested_func_name}"
                        )

                        try:
                            # Execute nested function recursively
                            nested_result = self._execute_node(nested_func_dict, variables)

                            # Check if result is an error
                            if isinstance(nested_result, dict) and "error" in nested_result:
                                logger.error(
                                    "      ❌ Nested function execution failed: "
                                    + nested_result.get("error_message", "Unknown error")
                                )
                                # Add parent function context to error
                                nested_result["parent_function"] = function_name
                                return nested_result

                            # Update parameter with nested function result
                            params[param_name] = nested_result
                            logger.debug(
                                f"      ✅ Updated parameter '{param_name}' with nested function result: {nested_result}"
                            )
                        except Exception as e:
                            logger.error(f"      ❌ Error executing nested function: {str(e)}", exc_info=True)
                            error_msg = (
                                "      ❌ Error in nested function '"
                                + nested_func_name
                                + "' for parameter '"
                                + param_name
                                + "': "
                                + str(e)
                            )
                            return {
                                "error": "nested_function_execution_failed",
                                "error_message": error_msg,
                                "function_name": nested_func_name,
                                "parent_function": function_name,
                            }

                # 4. Execute dependencies if needed
                if dependencies:
                    try:
                        # Resolve dependencies with updated parameters
                        params = self._resolve_dependencies(function_name, params)
                    except ValueError as e:
                        error_msg = str(e)
                        logger.error(f"      ❌ Dependency resolution failed: {error_msg}", exc_info=True)

                        # Check if this is a validation error with user-friendly message
                        if "Validation error from" in error_msg:
                            # Extract user-friendly message
                            parts = error_msg.split(": ", 1)
                            if len(parts) > 1:
                                user_error = parts[1]
                                # Return a structured error object for NLComposer
                                return {
                                    "error": "validation_failed",
                                    "error_message": user_error,
                                    "function_name": (
                                        error_msg.split("from ", 1)[1].split(":", 1)[0]
                                        if "from " in error_msg
                                        else "unknown"
                                    ),
                                    "details": error_msg,
                                }

                        # For other errors, return with context
                        return {
                            "error": "dependency_resolution_failed",
                            "error_message": error_msg,
                            "function_name": function_name,
                        }

                # Check for list parameter mismatches
                if hasattr(self, "auto_list_processing") and self.auto_list_processing:
                    list_param_info = self._check_for_list_param_mismatch(function_name, params)
                    if list_param_info:
                        logger.debug(
                            f"DEBUG - Detected list parameter mismatch for {function_name}, applying list processing"
                        )
                        return self._process_list_param(
                            function_name, params, list_param_info, getattr(self, "parallel_list_processing", False)
                        )

                # 5. Execute the function with the resolved parameters
                logger.info(
                    f"      🔄 [EXECUTING] {function_name}({', '.join([f'{k}=\"{v}\"' for k, v in params.items()])})"
                )
                try:
                    # Get function signature for filtering params
                    function_obj = self.registry.get_function(function_name)
                    sig = inspect.signature(function_obj)
                    param_names = [p for p in sig.parameters]

                    # Filter parameters based on function signature
                    filtered_params = {k: v for k, v in params.items() if k in param_names}

                    # Check for missing required parameters
                    for param_name, param in sig.parameters.items():
                        if param_name not in filtered_params and param.default == inspect.Parameter.empty:
                            error_msg = (
                                "      ❌ Missing required parameter '"
                                + param_name
                                + "' for function '"
                                + function_name
                                + "'"
                            )
                            logger.error("      ❌ " + error_msg, exc_info=True)
                            return {
                                "error": "missing_parameter",
                                "error_message": error_msg,
                                "function_name": function_name,
                            }

                    # Track execution time - start
                    start_time = time.time()

                    # Execute the function
                    logger.info(
                        "      🔄 [EXECUTING] "
                        + function_name
                        + "("
                        + ", ".join([f'{k}="{v}"' for k, v in filtered_params.items()])
                        + ")"
                    )
                    result = function_obj(**filtered_params)

                    # Track execution time - end
                    end_time = time.time()
                    execution_time = round(end_time - start_time, 2)
                    self.execution_times[function_name] = execution_time
                    logger.debug(f"DEBUG - Function {function_name} executed in {execution_time} seconds")

                    # Create a unique key for this specific function call using parameters
                    param_digest = str(sorted([(k, str(v)[:20]) for k, v in filtered_params.items()]))
                    unique_key = f"{function_name}_{hash(param_digest) & 0xffffffff:08x}"

                    # Create a simplified parameter representation for debug output
                    simplified_params = {
                        k: str(v)[:30] + ("..." if len(str(v)) > 30 else "") for k, v in filtered_params.items()
                    }

                    # Store detailed results with parameter context
                    self.function_outputs_detailed[unique_key] = {
                        "function_name": function_name,
                        "params": filtered_params.copy(),
                        "result": result,
                        "execution_time": execution_time,
                    }

                    # For backward compatibility, maintain the original function_outputs structure
                    # But store multiple calls in a list to avoid overwriting
                    if function_name in self.function_outputs:
                        # If not already a list, convert to list
                        if not isinstance(self.function_outputs[function_name], list):
                            self.function_outputs[function_name] = [self.function_outputs[function_name]]
                        # Append new result to the list
                        self.function_outputs[function_name].append(result)
                    else:
                        # First call to this function, store directly
                        self.function_outputs[function_name] = result

                    # Always update execution_results with the most recent result for dependency resolution
                    self.execution_results[function_name] = result

                    logger.info(f"      ✅ {function_name} returned: {result}")
                    logger.info(f"[STORAGE] Stored result with parameter summary: {simplified_params}")
                    return result
                except Exception as e:
                    logger.error(f"      ❌ Error executing {function_name}: {str(e)}", exc_info=True)
                    logger.error(f"      ❌ Traceback: {traceback.format_exc()}")

                    # Determine if this is a validation error
                    error_msg = str(e)
                    error_type = (
                        "validation_error"
                        if (
                            "validation" in error_msg.lower()
                            or "invalid" in error_msg.lower()
                            or "not found" in error_msg.lower()
                        )
                        else "execution_failed"
                    )

                    # Return a standardized error object
                    return {"error": error_type, "error_message": error_msg, "function_name": function_name}

            # Handle operations (like add)
            elif node_type == "operation":
                op_type = node.get("op")

                # Handle addition with potential parallelism
                if op_type == "add":
                    # Check if we should use parallel execution (controlled by parallel_list_processing)
                    if hasattr(self, "parallel_list_processing") and self.parallel_list_processing:
                        logger.debug("[PARALLEL] Executing both sides of '+' operation in parallel")
                        # Use ThreadPoolExecutor to execute both sides in parallel
                        with ThreadPoolExecutor() as executor:
                            # Submit both tasks
                            left_future = executor.submit(self._execute_node, node.get("left"), variables)
                            right_future = executor.submit(self._execute_node, node.get("right"), variables)
                            # Get results
                            left = left_future.result()
                            right = right_future.result()
                    else:
                        # Original sequential behavior
                        left = self._execute_node(node.get("left"), variables)
                        right = self._execute_node(node.get("right"), variables)

                    # Handle string concatenation
                    if isinstance(left, str) and isinstance(right, str):
                        return left + right

                    # Handle numeric addition
                    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                        return left + right

                    # Try to handle combination with __add__
                    try:
                        combined = None
                        if hasattr(left, "__add__"):
                            try:
                                combined = left + right
                                if combined is not NotImplemented:
                                    return combined
                            except Exception:
                                pass  # Fall through to next combination attempt

                        # Special handling for dictionaries
                        if isinstance(left, dict) and isinstance(right, dict):
                            try:
                                combined = {**left, **right}
                                return combined
                            except Exception:
                                pass  # Fall through to next combination attempt

                        # Return structured format combining both results
                        individual_results = [left, right]
                        if combined is None:
                            combined = f"{left} | {right}"

                        result_dict = {}
                        for i, result in enumerate(individual_results):
                            result_dict[f"result_{i}"] = result

                        return {
                            "combined": combined,
                            "individual_results": individual_results,
                            "result_dict": result_dict,
                        }
                    except Exception as e:
                        logger.error(f"      ❌ Error combining results: {str(e)}", exc_info=True)
                        # Concatenate as strings as a final fallback
                        return f"{left} | {right}"
                else:
                    logger.warning(f"      ❌ Unsupported operation type: {op_type}")
                    return None

        # Handle unexpected node types
        logger.warning(f"      ❌ Unknown node type: {node}")
        return None

    @measure_execution_time(log_prefix="Dependency resolution")
    def _resolve_dependencies(self, func_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Resolve function dependencies and update parameters.

        Args:
            func_name: The function name
            params: The parameters to update

        Returns:
            The updated parameters
        """
        dependencies = self.registry.get_dependencies(func_name)
        if not dependencies:
            return params

        logger.debug(f"      🔍 Found {len(dependencies)} runtime dependencies for {func_name}")
        logger.debug(f"      🔍 Dependencies: {dependencies}")
        logger.debug(f"      🔍 Initial params: {params}")

        # Create a cache for dependency results to avoid re-execution
        dependency_results = {}

        # Track functions we've already executed to avoid duplicates
        executed_functions = set()

        # First, check for any _func_ parameters and execute them if needed
        func_params_to_resolve = []
        for param_name, param_value in params.items():
            if isinstance(param_value, str) and param_value.startswith("_func_"):
                nested_func_name = param_value[6:]  # Remove _func_ prefix
                # Check if this is a registered dependency
                for dep in dependencies:
                    if dep.get("function") == nested_func_name and dep.get("map_result_to") == param_name:
                        func_params_to_resolve.append((param_name, nested_func_name))
                        break

        # Prepare dependencies for parallel execution
        parallel_tasks = []
        dependency_info = []

        for i, dependency in enumerate(dependencies):
            dep_func_name = dependency.get("function")
            result_param = dependency.get("map_result_to")

            # Skip if no function name
            if not dep_func_name:
                continue

            # Allow None as a special value meaning "execute but don't map result"
            # Only skip if result_param is missing (not None)
            if result_param is None:
                logger.debug(
                    "    ➤ Processing dependency "
                    + str(i + 1)
                    + "/"
                    + str(len(dependencies))
                    + ": "
                    + str(dep_func_name)
                )
                logger.debug("    ➤ Dependency will execute but result won't be mapped (map_result_to is None)")
            elif not result_param:
                continue

            logger.debug(
                "    ➤ Processing dependency " + str(i + 1) + "/" + str(len(dependencies)) + ": " + str(dep_func_name)
            )
            logger.debug("    ➤ Dependency details: " + str(dependency))

            # Check if this dependency has force_execution flag
            force_execution = dependency.get("force_execution", False)
            if force_execution:
                logger.info(
                    "      🚀 Force execution flag is set - will execute dependency even if parameter already exists"
                )

            # Check if this parameter is already directly provided in params (not as _func_)
            # Only check if result_param is not None and is not a dictionary (which indicates field mapping)
            # Skip this check if force_execution is set to True
            if (
                not force_execution
                and result_param is not None
                and not isinstance(result_param, dict)
                and result_param in params
                and not (isinstance(params[result_param], str) and params[result_param].startswith("_func_"))
            ):
                logger.info(
                    "      ✅ Parameter '"
                    + str(result_param)
                    + "' already provided with value: "
                    + str(params[result_param])
                )
                continue

            # Check if condition is met (if provided)
            condition = dependency.get("condition")
            condition_result = True
            if condition:
                try:
                    condition_result = condition(params)
                    if not condition_result:
                        logger.warning("      ⚠️ Skipping dependency " + str(dep_func_name) + " (condition not met)")
                        # Check if we need to execute the function directly because it was marked in params
                        if (
                            not isinstance(result_param, dict)
                            and result_param in params
                            and isinstance(params[result_param], str)
                            and params[result_param] == f"_func_{dep_func_name}"
                        ):
                            logger.info(
                                "      🔄 But executing anyway because it was referenced directly in parameters"
                            )
                        else:
                            continue
                except Exception as e:
                    logger.error(
                        "      ⚠️ Error evaluating condition for dependency " + str(dep_func_name) + ": " + str(e),
                        exc_info=True,
                    )
                    # Default to executing the dependency if condition evaluation fails
                    condition_result = True

            # Extract parameter mappings
            param_mapping = dependency.get("map_params", {})
            logger.debug("      🔍 Parent function params: " + str(params))
            logger.debug("      🔍 Parameter mapping config: " + str(param_mapping))

            # Create parameter dictionary for the dependency
            dep_params = {}
            for dep_param, parent_param in param_mapping.items():
                if parent_param in params:
                    dep_params[dep_param] = params[parent_param]
                    logger.debug(
                        "      ✅ Mapped parameter '"
                        + str(dep_param)
                        + "' to parent parameter '"
                        + str(parent_param)
                        + "' with value '"
                        + str(params[parent_param])
                        + "'"
                    )
                else:
                    logger.warning("      ⚠️ Parent parameter '" + str(parent_param) + "' not found in params dict")

            logger.debug("      📋 Final dependency parameters: " + str(dep_params))

            # Check if we've already executed this function with the same parameters
            dep_key = (dep_func_name, frozenset(dep_params.items()))
            if dep_key in executed_functions:
                logger.debug(
                    f"      🔍 Dependency {dep_func_name} already executed with these parameters - using cached result"
                )
                result = dependency_results[dep_key]
                # Store the result directly based on mapping configuration
                self._process_dependency_result(result, result_param, params, dep_func_name)
            else:
                # Add to the parallel execution queue
                logger.info(f"      🔄 Queueing dependency for parallel execution: {dep_func_name}")
                # Add this dependency to the tasks list for parallel execution
                parallel_tasks.append((dep_func_name, dep_params, dep_key))
                # Store the result parameter for later mapping
                dependency_info.append((dependency, result_param))

        # If we have tasks to execute in parallel
        if parallel_tasks:
            logger.info(f"    🚀 Executing {len(parallel_tasks)} dependencies in parallel")

            # Define the worker function to execute inside ThreadPoolExecutor
            def execute_dependency(task_info):
                dep_func_name, dep_params, dep_key = task_info
                try:
                    # Get the function from the registry
                    dep_func = self.registry.get_function(dep_func_name)
                    logger.info(
                        "      🔄 [PARALLEL] Executing: "
                        + dep_func_name
                        + "("
                        + ", ".join([f"{k}={v}" for k, v in dep_params.items()])
                        + ")"
                    )
                    start_time = time.time()
                    result = dep_func(**dep_params)
                    end_time = time.time()
                    logger.info(f"      ✓ [PARALLEL] Completed {dep_func_name} in {end_time - start_time:.2f}s")
                    return (dep_key, result, None)  # Return (key, result, error)
                except Exception as e:
                    logger.error(f"      ❌ [PARALLEL] Error executing {dep_func_name}: {str(e)}", exc_info=True)
                    logger.error(f"      ❌ [PARALLEL] Traceback: {traceback.format_exc()}")
                    return (dep_key, None, e)  # Return (key, None, error)

            # Execute all tasks in parallel using ThreadPoolExecutor
            with ThreadPoolExecutor() as executor:
                future_results = list(executor.map(execute_dependency, parallel_tasks))

            # Process results
            for (dep_key, result, error), (dependency, result_param) in zip(future_results, dependency_info):
                if error:
                    # Re-raise the exception
                    raise type(error)(str(error))

                # Store result in cache
                dependency_results[dep_key] = result
                executed_functions.add(dep_key)

                # Validate the result (if a validation function is provided)
                validator = dependency.get("validate_result")
                if validator:
                    try:
                        is_valid = validator(result)
                        if not is_valid:
                            # Try to extract a user-friendly error message from the validation result
                            user_error = None
                            if isinstance(result, dict) and "error" in result:
                                user_error = result["error"]
                            elif (
                                isinstance(result, dict)
                                and "valid" in result
                                and not result["valid"]
                                and "error" in result
                            ):
                                user_error = result["error"]

                            logger.error("      ❌ Dependency result validation failed for " + dep_key[0])

                            if user_error:
                                logger.error("      ❌ Validation error: " + user_error)
                                raise ValueError("Validation error from " + dep_key[0] + ": " + user_error)
                            else:
                                logger.error(
                                    "      ❌ Error validating dependency result: Dependency "
                                    + dep_key[0]
                                    + " failed validation"
                                )
                                raise ValueError("Dependency " + dep_key[0] + " failed validation")
                    except Exception as e:
                        if not isinstance(e, ValueError) or "Validation error from" not in str(e):
                            # Only add the generic error message if it's not already a formatted validation error
                            logger.error("      ❌ Error validating dependency result: " + str(e))
                            raise ValueError("Error validating dependency " + dep_key[0] + " result: " + str(e))
                        else:
                            # Re-raise the already formatted validation error
                            raise

                # Process the dependency result and update parameters
                self._process_dependency_result(result, result_param, params, dep_key[0])

        # Final check for any remaining _func_ parameters in the params that weren't resolved
        for param_name, param_value in list(params.items()):
            if isinstance(param_value, str) and param_value.startswith("_func_"):
                nested_func_name = param_value[6:]  # Remove _func_ prefix
                # Try to execute the function directly as a last resort
                try:
                    logger.debug(
                        "      🔄 Directly executing nested function for unresolved parameter: "
                        + nested_func_name
                        + "()"
                    )
                    nested_func = self.registry.get_function(nested_func_name)
                    nested_result = nested_func()
                    params[param_name] = nested_result
                    logger.info("      ✅ Updated parameter '" + param_name + "' to actual value: " + nested_result)
                except Exception as e:
                    logger.error(
                        "      ❌ Error executing nested function '" + nested_func_name + "': " + str(e), exc_info=True
                    )

        logger.debug("    ➤ Final resolved parameters: " + str(params))
        return params

    def _process_dependency_result(self, result, result_param, params, dep_func_name):
        """Process a dependency result and update parameters accordingly.

        Args:
            result: The result from the dependency function
            result_param: The mapping configuration (string, dict, or None)
            params: The parameters to update
            dep_func_name: The name of the dependency function (for logging)
        """
        # Don't do anything if result_param is None
        if result_param is None:
            logger.warning("      📍 Dependency executed but result not mapped (map_result_to was None)")
            return

        # If result_param is a string, this is direct parameter mapping
        if isinstance(result_param, str):
            logger.info("      📍 Mapping entire result to parameter: " + result_param)
            params[result_param] = result
            logger.info("      📍 Updated params after mapping: " + str(params))
            return

        # If result_param is a dictionary, this is field-specific mapping
        if isinstance(result_param, dict):
            logger.info("      📍 Field-specific mapping from dependency result")
            for target_param, field_path in result_param.items():
                # Handle field_path that could be a string or a dict with advanced options
                if isinstance(field_path, dict):
                    source_path = field_path.get("path")
                    transform = field_path.get("transform")
                    default_value = field_path.get("default")
                else:
                    source_path = field_path
                    transform = None
                    default_value = None

                # Extract the value from the result
                if source_path is None:
                    logger.warning("      ⚠️ No field path specified for " + target_param)
                    continue

                value = None
                # Direct field access for simple cases
                if isinstance(result, dict) and source_path in result:
                    value = result[source_path]
                    logger.info("      📍 Found field '" + source_path + "' directly in result: " + str(value))
                else:
                    # Use path resolution for more complex cases
                    value = self._resolve_path(result, source_path)
                    logger.info("      📍 Resolved path '" + source_path + "' from result: " + str(value))

                # Apply default if needed
                if value is None and default_value is not None:
                    value = default_value
                    logger.info("      📍 Using default value for '" + target_param + "': " + str(default_value))

                # Apply transformation if specified
                if transform is not None and value is not None:
                    try:
                        if isinstance(transform, type):
                            value = transform(value)
                        elif callable(transform):
                            value = transform(value)
                        logger.info("      📍 Applied transformation to value: " + str(value))
                    except Exception as e:
                        logger.error("      ⚠️ Error applying transformation: " + str(e), exc_info=True)

                # Update the parameter if we got a value
                if value is not None:
                    logger.info(
                        "      📍 Updating parameter '"
                        + target_param
                        + "' with value from field '"
                        + source_path
                        + "': "
                        + str(value)
                    )
                    params[target_param] = value
                else:
                    logger.warning(
                        "      ⚠️ Could not get value for '" + target_param + "' from field '" + source_path + "'"
                    )

        # If result_param is something else (shouldn't happen), log a warning
        else:
            logger.warning("      ⚠️ Unknown map_result_to configuration type: " + str(type(result_param)))

    def _format_combined_results(self, results, all_dicts=False):
        """Format the results from multiple function executions."""
        logger.debug("      🔍 Formatting combined results from " + str(len(results)) + " functions")
        for i, result in enumerate(results):
            logger.debug("      🔍 Result " + str(i + 1) + ": " + str(type(result)) + " - " + str(result))

        if not results:
            return "No results found"

        # Handle error results
        errors = [r for r in results if isinstance(r, dict) and "error" in r]
        if errors:
            error_msgs = [f"{r.get('function_name', 'unknown')}: {r['error_message']}" for r in errors]
            return {
                "error": "execution_failed",
                "error_messages": error_msgs,
                "partial_results": [r for r in results if not (isinstance(r, dict) and "error" in r)],
            }

        # Process successful results
        if all_dicts:
            # Merge all dictionary results
            merged_dict = {}
            individual_results = []
            result_str_parts = []

            for result in results:
                if isinstance(result, dict):
                    # Handle structured results
                    if "function" in result and "result" in result:
                        function_name = result["function"]
                        result_data = result["result"]
                        individual_results.append(result_data)

                        if isinstance(result_data, dict):
                            for key, value in result_data.items():
                                merged_key = f"{function_name}_{key}"
                                merged_dict[merged_key] = value
                            result_str = f"{function_name} result:\n" + "\n".join(
                                [f"  {k}: {v}" for k, v in result_data.items()]
                            )
                            result_str_parts.append(result_str)
                    else:
                        # Direct dictionary result
                        individual_results.append(result)
                        for key, value in result.items():
                            merged_dict[key] = value
                        result_str = "\n".join([f"  {k}: {v}" for k, v in result.items()])
                        result_str_parts.append(result_str)
                else:
                    # Non-dictionary result
                    individual_results.append(result)
                    result_str_parts.append(str(result))

            combined_string = " | ".join(result_str_parts)

            return {
                "combined": combined_string,
                "merged": merged_dict,
                "individual_results": individual_results,
                "result_dict": merged_dict,
            }
        else:
            # Convert all results to strings
            string_results = []
            for result in results:
                if isinstance(result, dict):
                    if "function" in result and "result" in result:
                        function_name = result["function"]
                        result_data = result["result"]
                        if isinstance(result_data, dict):
                            result_str = f"{function_name} result:\n" + "\n".join(
                                [f"  {k}: {v}" for k, v in result_data.items()]
                            )
                        else:
                            result_str = f"{function_name} result: {str(result_data)}"
                    else:
                        result_str = "\n".join([f"  {k}: {v}" for k, v in result.items()])
                    string_results.append(result_str)
                else:
                    string_results.append(str(result))

            return "\n\n".join(string_results)

    def _check_for_list_param_mismatch(self, function_name: str, params: Dict[str, Any]) -> Optional[Dict]:
        """Check if a function has a parameter that is a list but expects a single value.

        Args:
            function_name: The name of the function to check
            params: The parameters to pass to the function

        Returns:
            Dict with mismatch info, or None if no mismatch found
        """
        function_obj = self.registry.get_function(function_name)
        if not function_obj:
            return None

        # Get the function signature to check param types
        sig = inspect.signature(function_obj)

        # Check each param
        for param_name, param_value in params.items():
            # Skip if the parameter isn't in the signature
            if param_name not in sig.parameters:
                continue

            # Skip if the value is not a list
            if not isinstance(param_value, list):
                continue

            # Skip empty lists
            if not param_value:
                continue

            # Get the parameter's annotation
            param = sig.parameters[param_name]
            annotation = param.annotation

            # If the annotation is List or similar, this is expected to be a list
            if hasattr(annotation, "__origin__") and annotation.__origin__ is list:
                continue

            if annotation == inspect.Parameter.empty:
                # If there's no type annotation, examine the docstring for clues
                doc = inspect.getdoc(function_obj) or ""
                param_doc_pattern = rf"(Args|Parameters):[^:]*{param_name}[^:]*:([^\n]*)"
                param_doc_match = re.search(param_doc_pattern, doc, re.IGNORECASE)
                if param_doc_match:
                    param_doc = param_doc_match.group(2)
                    if "list" in param_doc.lower():
                        continue  # Docstring suggests list is expected

            # If we get here, we found a mismatch - this param expects a single value but got a list
            return {"param_name": param_name, "param_value": param_value, "function_name": function_name}

        return None

    @measure_execution_time(log_prefix="List parameter processing")
    def _process_list_param(
        self, function_name: str, params: Dict[str, Any], list_param_info: Dict, parallel: bool = False
    ) -> Any:
        """Process a function call with a list parameter.

        Args:
            function_name: The name of the function to execute
            params: The parameters to pass to the function
            list_param_info: Information about the list parameter to process
            parallel: Whether to process the list in parallel

        Returns:
            The combined results of executing the function with each item in the list
        """
        param_name = list_param_info["param_name"]
        list_values = list_param_info["param_value"]

        # Create a list to hold results
        results = []

        if parallel:
            # Process in parallel using ThreadPoolExecutor
            with ThreadPoolExecutor() as executor:
                # Create a processing function that captures the current context
                def process_item(item_info):
                    item_value, idx = item_info
                    try:
                        # Create a copy of parameters with this specific item
                        item_params = params.copy()
                        item_params[param_name] = item_value

                        # Log what we're doing
                        logger.info(
                            f"[PARALLEL] Processing item {idx+1}/{len(list_values)} for {param_name}: {item_value}"
                        )

                        # Process this item and return the result
                        function_obj = self.registry.get_function(function_name)
                        result = function_obj(**item_params)

                        logger.info(f"[PARALLEL] Completed item {idx+1}/{len(list_values)}")
                        return result
                    except Exception as e:
                        logger.error(f"[ERROR] Error processing item {idx+1}/{len(list_values)}: {str(e)}")
                        return {"error": f"Error processing item {idx+1}: {str(e)}"}

                # Submit all items for parallel processing
                future_to_idx = {
                    executor.submit(process_item, (item, idx)): idx for idx, item in enumerate(list_values)
                }

                # Collect results as they complete
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as e:
                        logger.error(f"[ERROR] Parallel processing error: {str(e)}")
                        results.append({"error": f"Parallel processing error: {str(e)}"})
        else:
            # Process sequentially
            for idx, item_value in enumerate(list_values):
                try:
                    # Create a copy of parameters with this specific item
                    item_params = params.copy()
                    item_params[param_name] = item_value

                    # Log what we're doing
                    logger.info(
                        f"[SEQUENTIAL] Processing item {idx+1}/{len(list_values)} for {param_name}: {item_value}"
                    )

                    # Process this item
                    function_obj = self.registry.get_function(function_name)
                    result = function_obj(**item_params)

                    # Store the result
                    results.append(result)
                    logger.info(f"[SEQUENTIAL] Completed item {idx+1}/{len(list_values)}")
                except Exception as e:
                    logger.error(f"[ERROR] Error processing item {idx+1}/{len(list_values)}: {str(e)}")
                    results.append({"error": f"Error processing item {idx+1}: {str(e)}"})

        # Combine all results
        return self._combine_list_results(results, function_name, list_values, param_name)

    def _combine_list_results(
        self, results: List[Any], function_name: str, list_values: List[Any], param_name: str
    ) -> Any:
        """Combine the results from multiple function executions.

        Args:
            results: List of individual results
            function_name: The function name that was executed
            list_values: The list of values that were processed
            param_name: The parameter name that contained the list

        Returns:
            Combined result object
        """
        # If there's only one result, just return it
        if len(results) == 1:
            return results[0]

        # Check if all results are dictionaries with the same keys
        all_dicts = all(isinstance(r, dict) for r in results)
        if all_dicts:
            # Check if all dictionaries have the same keys
            keys_sets = [set(r.keys()) for r in results]
            all_same_keys = all(ks == keys_sets[0] for ks in keys_sets)

            if all_same_keys:
                # Combine dictionaries by key
                combined_dict = {}
                for key in keys_sets[0]:
                    combined_dict[key] = [r[key] for r in results]

                return {
                    "combined": self._format_combined_results(combined_dict, all_dicts=True),
                    "individual_results": results,
                    "result_dict": combined_dict,
                }

        # For strings, we can try to join them
        if all(isinstance(r, str) for r in results):
            combined = " | ".join(results)

            # Create result_dict using a loop instead of comprehension
            result_dict = {}
            for i in range(len(results)):
                result_dict[f"{param_name}_{i}"] = list_values[i] if i < len(list_values) else "unknown"
                result_dict[f"result_{i}"] = results[i]

            return {"combined": combined, "individual_results": results, "result_dict": result_dict}

        # For other types, return a structured result
        # Create result_dict using a loop instead of comprehension
        result_dict = {}
        for i in range(len(results)):
            result_dict[f"{param_name}_{i}"] = list_values[i] if i < len(list_values) else "unknown"
            result_dict[f"result_{i}"] = results[i]

        return {
            "combined": self._format_combined_results(results),
            "individual_results": results,
            "result_dict": result_dict,
        }


class FunctionComposer:
    """Main class for composing and executing functions."""

    def __init__(self, app_name="default"):
        """Initialize the composer with an empty registry.

        Args:
            app_name: Name of the application for conversation tracking
        """
        self.registry = FunctionRegistry()
        self.planner = ExecutionPlanner(self.registry)
        self.parser = FunctionParser(self.registry)
        self.executor = FunctionExecutor(self.registry, self.parser)
        # Create a dictionary to store execution results for dependency resolution
        self.executor.execution_results = {}

        # Initialize conversation support
        self.app_name = app_name
        self._init_conversation_manager()

    def _init_conversation_manager(self):
        """Initialize the conversation manager if available."""
        try:
            self.conversation_manager = ConversationManager(default_app_name=self.app_name)
            self._has_conversation_support = True
        except ImportError:
            # Conversation support is optional
            self._has_conversation_support = False

    def register(self, func=None, *, name=None, dependencies=None):
        """Register a function."""
        return self.registry.register(func, name=name, dependencies=dependencies)

    def parse(self, expression: str) -> bool:
        """Parse and validate a function composition expression."""
        try:
            ast.parse(expression)
            return True
        except SyntaxError:
            return False

    def start_conversation(self, app_name=None, user_id=None) -> str:
        """Start a new conversation and return its ID.

        Args:
            app_name: Name of the application (defaults to self.app_name)
            user_id: Optional user identifier

        Returns:
            str: The UUID of the created conversation
        """
        if not self._has_conversation_support:
            raise RuntimeError(
                "Conversation support is not available. " "Please ensure the conversation_manager module is installed."
            )

        app_name = app_name or self.app_name
        return self.conversation_manager.create_conversation(app_name, user_id)

    def get_registered_functions(self):
        """Get a dictionary of all registered functions.

        Returns:
            dict: Dictionary mapping function names to function objects
        """
        if not hasattr(self, "registry"):
            return {}

        return self.registry.functions

    def get_function_outputs(self):
        """Get the function outputs from the most recent execution.

        Returns:
            dict: A dictionary mapping function names to their outputs
        """
        if hasattr(self, "executor") and hasattr(self.executor, "get_function_outputs"):
            return self.executor.get_function_outputs()
        return {}

    def get_execution_times(self):
        """Get the execution times for each function.

        Returns:
            dict: A dictionary mapping function names to their execution times in seconds
        """
        if hasattr(self, "executor"):
            return self.executor.execution_times
        return {}

    def get_performance_metrics(self):
        """Get all performance metrics tracked by the system.

        Returns:
            dict: A dictionary containing performance metrics
        """
        return get_performance_metrics()

    def reset_performance_metrics(self):
        """Reset all performance metrics."""
        reset_performance_metrics()

    @measure_execution_time(log_prefix="Function composition execution", metadata_key="total_execution_time")
    def execute(
        self,
        expression: str,
        variables: Dict = None,
        auto_list_processing: bool = True,
        parallel_list_processing: bool = False,
        return_metrics: bool = False,
        metadata: Dict = None,
    ) -> Any:
        """Execute a function composition using the execution planner.

        Args:
            expression: The function composition expression
            variables: Optional dictionary of variable values
            auto_list_processing: Whether to automatically process list parameters (when a function
                                 returns a list but the next function expects a single value)
            parallel_list_processing: Whether to process list parameters in parallel (when auto_list_processing is True)
            return_metrics: Whether to return performance metrics along with the result
            metadata: Optional dictionary to store timing information

        Returns:
            The result of executing the function composition, or if return_metrics is True,
            a dictionary containing the result and performance metrics
        """
        logger.info("\n=== EXECUTION PLAN START ===")
        logger.info(f"Function Composition: {expression}")

        # Add log message for parallel execution
        if parallel_list_processing:
            logger.info("⚡ PARALLEL EXECUTION ENABLED - Independent functions with '+' operator will run in parallel")

        # Reset the function output tracking before execution
        self.executor.reset_tracking()

        # Generate execution plan
        plan = self.planner.analyze_expression(expression)

        # Display the execution plan
        logger.info("\n" + plan.visualize() + "\n")

        # Use the executor to execute the expression
        logger.info("STARTING EXECUTION")

        start_time = time.time()
        result = self.executor.execute(
            expression,
            variables or {},
            auto_list_processing=auto_list_processing,
            parallel_list_processing=parallel_list_processing,
            metadata=metadata,
        )
        execution_time = time.time() - start_time

        # Display the final execution statistics
        logger.info(f"EXECUTION COMPLETED IN {execution_time:.4f} SECONDS")

        # Calculate execution statistics
        stats = plan.calculate_execution_stats()
        logger.info(f"EXECUTION STATISTICS: {stats}")

        logger.info("=== EXECUTION PLAN END ===\n")

        if return_metrics:
            # Get the execution plan metrics
            plan_metrics = plan.get_performance_report()

            # Get the global function metrics
            function_metrics = get_performance_metrics()

            # Return both the result and the metrics
            return {
                "result": result,
                "execution_time": execution_time,
                "plan_metrics": plan_metrics,
                "function_metrics": function_metrics,
            }

        # Return just the result if metrics not requested
        return result
