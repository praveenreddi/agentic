"""
Visualization utilities for the function composition framework.

This module provides functions for visualizing various aspects of the framework,
including execution plans, dependency resolution, and function execution.
"""

import ast
import inspect
from agentic_inventory.utils.extensions import logger


def visualize_ast(tree, expression: str):
    """Visualize an Abstract Syntax Tree (AST) for a function composition expression."""
    logger.info("\n" + "=" * 80)
    logger.info("STEP 1: EXECUTION PLAN CONSTRUCTION PROCESS")
    logger.info("=" * 80)
    logger.info("\n📊 Abstract Syntax Tree (AST) for expression:")
    logger.info(f"📝 Original expression: {expression}")

    def format_ast_node(node, depth=0, get_function_name=None):
        """Format an AST node for visualization."""
        indent = "  " * depth
        node_type = type(node).__name__

        if isinstance(node, ast.Call):
            func_name = get_function_name(node) if get_function_name else "unknown"
            args = [format_ast_node(arg, depth + 1, get_function_name) for arg in node.args]
            kwargs = {kw.arg: format_ast_node(kw.value, depth + 1, get_function_name) for kw in node.keywords}
            return (
                f"{indent}📞 Call: {func_name}(\n"
                + "\n".join([f"{indent}  Arg{i}: {arg}" for i, arg in enumerate(args)])
                + ("\n" if args else "")
                + "\n".join([f"{indent}  {k}={v}" for k, v in kwargs.items()])
                + f"\n{indent})"
            )
        elif isinstance(node, ast.Constant):
            return f"{indent}📌 Constant: {repr(node.value)}"
        elif isinstance(node, ast.Name):
            return f"{indent}🔤 Name: {node.id}"
        elif isinstance(node, ast.BinOp):
            op_name = type(node.op).__name__
            return (
                f"{indent}🔣 BinOp: {op_name}\n"
                + f"{indent}  Left: {format_ast_node(node.left, depth + 2, get_function_name)}\n"
                + f"{indent}  Right: {format_ast_node(node.right, depth + 2, get_function_name)}"
            )
        else:
            return f"{indent}🔹 {node_type}"

    for node in ast.iter_child_nodes(tree):
        logger.info(format_ast_node(node))
    logger.info("\n" + "-" * 80 + "\n")


def visualize_runtime_dependencies(nodes, node_map, registry):
    """Visualize runtime dependencies for all functions in the execution plan."""
    logger.info("\n" + "=" * 80)
    logger.info("STEP 2: RESOLVING RUNTIME DEPENDENCIES")
    logger.info("=" * 80)
    logger.info("\n🔄 Analyzing registered runtime dependencies for each function...")

    runtime_dep_map = {}
    if registry:
        for node in nodes:
            # Get registered dependencies for this function
            registered_deps = registry.get_dependencies(node.job_name)

            logger.info(f"\n📋 Function: {node.job_name}")
            logger.info(f"   Parameters: {node.params}")

            if registered_deps:
                logger.info(f"   Has {len(registered_deps)} registered dependencies:")

                runtime_deps = set()
                # Collect runtime dependencies for tracking
                for i, dep in enumerate(registered_deps, 1):
                    dep_func_name = dep.get("function")
                    if dep_func_name:
                        logger.info(f"   {i}. Dependency: {dep_func_name}")

                        if "map_params" in dep:
                            logger.info(f"      Parameter mapping: {dep['map_params']}")

                        if "map_result_to" in dep:
                            logger.info(f"      Result maps to: {dep['map_result_to']}")

                        if "condition" in dep:
                            condition_source = inspect.getsource(dep["condition"]).strip()
                            logger.info(f"      Conditional execution: {condition_source}")

                        if "validate_result" in dep:
                            validation_source = inspect.getsource(dep["validate_result"]).strip()
                            logger.info(f"      Result validation: {validation_source}")

                        runtime_deps.add(dep_func_name)

                        if dep_func_name not in node_map:
                            logger.info(f"      📌 Created new node for dependency: {dep_func_name}")
                        else:
                            logger.info(f"      📎 Updated existing node: {dep_func_name}")

                # Store runtime deps in temporary map
                runtime_dep_map[node.job_name] = runtime_deps
            else:
                logger.info("Has no registered dependencies.")

    logger.info("\n" + "-" * 80)
    return runtime_dep_map


def visualize_circular_dependency_detection(node_map, runtime_dep_map):
    """Visualize the process of circular dependency detection using DFS."""
    logger.info("\n" + "=" * 80)
    logger.info("STEP 3: CIRCULAR DEPENDENCY DETECTION")
    logger.info("=" * 80)
    logger.info("\n🔍 Performing depth-first search for circular dependency detection...")

    # Track visited nodes for visualization
    dfs_visited_order = []

    def has_circular_path(node_name, visited=None, path=None):
        if visited is None:
            visited = set()
        if path is None:
            path = []

        # For visualization
        current_path = path.copy()
        current_path.append(node_name)
        path_str = " → ".join(current_path)
        dfs_visited_order.append(node_name)

        # First check if we've found a cycle
        if node_name in path:
            cycle_path = path + [node_name]
            logger.warning(f"   ⚠️ CYCLE DETECTED: {' → '.join(cycle_path)}")
            return True

        # If we've already visited this node and didn't find a cycle, don't recheck
        if node_name in visited:
            logger.debug(f"   ↩️ Already visited: {node_name}, skipping")
            return False

        # Skip nodes that don't exist in either dependency map
        if node_name not in node_map and node_name not in runtime_dep_map:
            logger.debug(f"   ❓ Node not found: {node_name}, skipping")
            return False

        # Add to tracking structures before recursing
        visited.add(node_name)
        path.append(node_name)

        logger.debug(f"   🔍 Visiting: {node_name} (Path: {path_str})")

        # Check AST dependencies (from direct function calls)
        if node_name in node_map:
            deps = node_map[node_name].dependencies
            if deps:
                logger.debug(f"     Checking {len(deps)} AST dependencies: {deps}")
                for dep in deps:
                    # Always make a copy of the path to avoid modifications affecting other recursion branches
                    if has_circular_path(dep, visited, path.copy()):
                        return True
            else:
                logger.debug("     No AST dependencies")

        # Check runtime dependencies (from function registry)
        if node_name in runtime_dep_map:
            runtime_deps = runtime_dep_map[node_name]
            if runtime_deps:
                logger.debug(f"     Checking {len(runtime_deps)} runtime dependencies: {runtime_deps}")
                for dep in runtime_deps:
                    # Always make a copy of the path to avoid modifications affecting other recursion branches
                    if has_circular_path(dep, visited, path.copy()):
                        return True
            else:
                logger.debug("     No runtime dependencies")

        # No circular dependencies were found
        logger.debug(f"   ✅ No cycles found from: {node_name}")
        path.pop()  # Remove the current node from the path before returning
        return False

    # Check for circular dependencies
    all_nodes = set(node_map.keys())
    all_nodes.update(runtime_dep_map.keys())

    logger.info(f"\n🧪 Testing {len(all_nodes)} nodes for circular dependencies...")
    for node_name in all_nodes:
        logger.info(f"\n🔄 Starting DFS from root: {node_name}")
        if has_circular_path(node_name):
            raise ValueError(f"Circular dependency detected involving function: {node_name}")

    logger.info("\n🎉 No circular dependencies detected!")

    # Visualization of DFS traversal
    logger.info("\n📊 DFS Traversal Order:")
    logger.info(f"   {' → '.join(dfs_visited_order)}")
    logger.info("\n" + "-" * 80)

    return has_circular_path


def visualize_execution_order(nodes, parallel_groups, sequential_nodes, dependency_graph):
    """Visualize the process of determining function execution order."""
    logger.info("\n" + "=" * 80)
    logger.info("STEP 4: FUNCTION EXECUTION ORDER ALGORITHM")
    logger.info("=" * 80)

    # Identify independent functions
    independent_nodes = [node for node in nodes if not node.dependencies]

    logger.info("\n🔍 Identifying independent functions (no dependencies):")
    if independent_nodes:
        logger.info(f"   Found {len(independent_nodes)} independent functions:")
        for i, node in enumerate(independent_nodes, 1):
            logger.info(f"   {i}. {node.job_name} - Can run independently")
    else:
        logger.info("   No independent functions found.")

    # Show topological sort information
    remaining = [node for node in nodes if node.dependencies]
    logger.info(f"\n📋 Applying topological sort to {len(remaining)} dependent functions...")

    # Visualize the dependency graph
    logger.info("\n📊 Dependency Graph:")
    for node_name, deps in dependency_graph.items():
        if deps:
            logger.info(f"   {node_name} depends on: {', '.join(deps)}")
        else:
            logger.info(f"   {node_name}: No dependencies")

    # Visualize final execution plan
    logger.info("\n📊 FINAL EXECUTION PLAN:")
    logger.info("\n   Parallel Groups:")
    for i, group in enumerate(parallel_groups, 1):
        logger.info(f"   Group {i}: {[node.job_name for node in group]}")

    logger.info("\n   Sequential Execution Order:")
    for i, node in enumerate(sequential_nodes, 1):
        logger.info(f"   {i}. {node.job_name}")


def visualize_dependency_resolution(func_name, params, dependencies, registry):
    """Visualize the process of resolving function dependencies."""
    logger.info("\n" + "=" * 80)
    logger.info("STEP 5: DEPENDENCY RESOLUTION")
    logger.info("=" * 80)
    logger.info(f"\n🔍 Resolving dependencies for function: {func_name}")
    logger.info(f"   Initial parameters: {params}")

    if dependencies:
        logger.info(f"\n📋 Found {len(dependencies)} dependencies:")
        for i, dep in enumerate(dependencies, 1):
            dep_func_name = dep.get("function")
            if dep_func_name:
                logger.info(f"\n   {i}. Dependency: {dep_func_name}")
                logger.info(f"      Parameter mapping: {dep.get('map_params', {})}")
                logger.info(f"      Result mapping: {dep.get('map_result_to', 'None')}")

                # Check if dependency is already satisfied
                result_param = dep.get("map_result_to")
                if result_param and result_param in params:
                    logger.info(f"      ✅ Dependency already satisfied with value: {params[result_param]}")
                else:
                    logger.info("      ⏳ Dependency needs to be resolved")

                # Show condition if present
                if "condition" in dep:
                    condition_source = inspect.getsource(dep["condition"]).strip()
                    logger.info(f"      Conditional execution: {condition_source}")

                # Show validation if present
                if "validate_result" in dep:
                    validation_source = inspect.getsource(dep["validate_result"]).strip()
                    logger.info(f"      Result validation: {validation_source}")
    else:
        logger.info("\n📋 No dependencies found.")

    logger.info("\n" + "-" * 80)


def visualize_function_execution(expression, variables, graph_type, execution_time, result):
    """Visualize the execution of a function composition."""
    logger.info("\n" + "=" * 80)
    logger.info("STEP 6: FUNCTION EXECUTION")
    logger.info("=" * 80)
    logger.info(f"\n📝 Expression: {expression}")
    logger.info(f"   Variables: {variables}")
    logger.info(f"   Graph Type: {graph_type}")
    logger.info(f"   Execution Time: {execution_time:.4f} seconds")

    if isinstance(result, dict) and "error" in result:
        logger.error(f"\n❌ Execution failed: {result['error_message']}")
    else:
        logger.info(f"\n✅ Execution successful: {result}")

    logger.info("\n" + "-" * 80)


def visualize_parallel_execution_results(nodes, results, execution_times):
    """Visualize the results of parallel function execution."""
    logger.info("\n" + "=" * 80)
    logger.info("STEP 7: PARALLEL EXECUTION RESULTS")
    logger.info("=" * 80)

    logger.info("\n📊 Execution Results:")
    for i, (node, result) in enumerate(zip(nodes, results), 1):
        execution_time = execution_times.get(node.job_name, 0)
        logger.info(f"\n   {i}. Function: {node.job_name}")
        logger.info(f"      Execution Time: {execution_time:.4f} seconds")
        if isinstance(result, dict) and "error" in result:
            logger.error(f"      ❌ Error: {result['error_message']}")
        else:
            logger.info(f"      ✅ Result: {result}")

    logger.info("\n" + "-" * 80)
