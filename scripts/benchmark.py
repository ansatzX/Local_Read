#!/usr/bin/env python3
"""
Simple performance benchmark for Local_Read backends.

This script benchmarks the Simple backend performance with various file types.
"""

import tempfile
import time
from pathlib import Path
from typing import Dict, Any, List
import statistics

from local_read.backends import get_registry, BackendType
from local_read.output_manager import OutputManager


def create_test_text_file(path: Path, size_kb: int = 10) -> None:
    """Create a test text file of specified size."""
    # Generate repeating content
    base_content = """# Test Document

This is a test document for benchmarking.

## Section 1

Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor
incididunt ut labore et dolore magna aliqua.

### Subsection 1.1

Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut
aliquip ex ea commodo consequat.

- Item 1
- Item 2
- Item 3

## Section 2

Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore
eu fugiat nulla pariatur.

| Column 1 | Column 2 | Column 3 |
|----------|----------|----------|
| Value 1  | Value 2  | Value 3  |
| Value 4  | Value 5  | Value 6  |

"""
    content = base_content
    while len(content.encode('utf-8')) < size_kb * 1024:
        content += base_content

    path.write_text(content)


def create_test_json_file(path: Path, size_kb: int = 10) -> None:
    """Create a test JSON file of specified size."""
    import json

    data = {
        "metadata": {
            "name": "Test JSON",
            "version": "1.0.0",
            "description": "Test file for benchmarking"
        },
        "items": []
    }

    # Generate items until we reach the desired size
    item_template = {
        "id": 0,
        "name": "Test Item",
        "description": "This is a test item for benchmarking purposes",
        "properties": {
            "key1": "value1",
            "key2": "value2",
            "key3": ["a", "b", "c"]
        }
    }

    item_id = 1
    while len(json.dumps(data, ensure_ascii=False).encode('utf-8')) < size_kb * 1024:
        item = item_template.copy()
        item["id"] = item_id
        item["name"] = f"Test Item {item_id}"
        data["items"].append(item)
        item_id += 1

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def benchmark_backend(
    backend,
    test_files: List[Path],
    iterations: int = 3
) -> Dict[str, Any]:
    """Benchmark a backend with test files."""
    results = {
        "backend_name": backend.name,
        "iterations": iterations,
        "files": []
    }

    for test_file in test_files:
        file_results = {
            "file_name": test_file.name,
            "file_size_kb": test_file.stat().st_size / 1024,
            "times": [],
            "success": 0,
            "failed": 0
        }

        for i in range(iterations):
            start_time = time.perf_counter()
            try:
                format = test_file.suffix.lstrip('.') or 'text'
                # Map extension to backend format
                format_map = {
                    'txt': 'text', 'md': 'text', 'py': 'text',
                    'json': 'json', 'csv': 'csv', 'yaml': 'yaml', 'yml': 'yaml',
                    'pdf': 'pdf', 'docx': 'word', 'doc': 'word',
                    'xlsx': 'excel', 'xls': 'excel',
                    'pptx': 'ppt', 'ppt': 'ppt',
                    'html': 'html', 'htm': 'html',
                    'zip': 'zip'
                }
                backend_format = format_map.get(format, format)

                result = backend.process(test_file, backend_format)
                elapsed = time.perf_counter() - start_time
                file_results["times"].append(elapsed)
                file_results["success"] += 1
            except Exception as e:
                elapsed = time.perf_counter() - start_time
                file_results["times"].append(elapsed)
                file_results["failed"] += 1

        # Calculate statistics
        if file_results["times"]:
            file_results["mean_time"] = statistics.mean(file_results["times"])
            file_results["median_time"] = statistics.median(file_results["times"])
            file_results["stdev_time"] = statistics.stdev(file_results["times"]) if len(file_results["times"]) > 1 else 0
            file_results["min_time"] = min(file_results["times"])
            file_results["max_time"] = max(file_results["times"])

        results["files"].append(file_results)

    # Calculate overall statistics
    all_times = []
    for file_result in results["files"]:
        all_times.extend(file_result["times"])

    if all_times:
        results["overall_mean"] = statistics.mean(all_times)
        results["overall_median"] = statistics.median(all_times)
        results["overall_stdev"] = statistics.stdev(all_times) if len(all_times) > 1 else 0

    return results


def print_benchmark_results(results: Dict[str, Any]) -> None:
    """Print benchmark results in a readable format."""
    print("=" * 80)
    print(f"Benchmark Results: {results['backend_name']}")
    print("=" * 80)
    print(f"\nIterations per file: {results['iterations']}")

    for file_result in results["files"]:
        print(f"\n--- {file_result['file_name']} ---")
        print(f"  Size: {file_result['file_size_kb']:.2f} KB")
        print(f"  Success: {file_result['success']}, Failed: {file_result['failed']}")

        if file_result["times"]:
            print(f"  Mean: {file_result['mean_time']*1000:.2f} ms")
            print(f"  Median: {file_result['median_time']*1000:.2f} ms")
            print(f"  Min: {file_result['min_time']*1000:.2f} ms")
            print(f"  Max: {file_result['max_time']*1000:.2f} ms")
            if file_result["stdev_time"] > 0:
                print(f"  Std Dev: {file_result['stdev_time']*1000:.2f} ms")

    if "overall_mean" in results:
        print(f"\n--- Overall ---")
        print(f"  Mean: {results['overall_mean']*1000:.2f} ms")
        print(f"  Median: {results['overall_median']*1000:.2f} ms")
        if results["overall_stdev"] > 0:
            print(f"  Std Dev: {results['overall_stdev']*1000:.2f} ms")


def main():
    """Run benchmarks."""
    print("=" * 80)
    print("Local_Read Backend Benchmark")
    print("=" * 80)

    registry = get_registry()

    benchmark_root = Path.cwd() / ".local_read_mcp" / "benchmarks"
    benchmark_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=benchmark_root) as tmpdir:
        tmp_path = Path(tmpdir)

        # Create test files
        print("\nCreating test files...")
        test_files = []

        # Text file (10 KB)
        txt_file = tmp_path / "test_10kb.txt"
        create_test_text_file(txt_file, size_kb=10)
        test_files.append(txt_file)
        print(f"  Created: {txt_file.name} ({txt_file.stat().st_size/1024:.2f} KB)")

        # Text file (50 KB)
        txt_file_large = tmp_path / "test_50kb.txt"
        create_test_text_file(txt_file_large, size_kb=50)
        test_files.append(txt_file_large)
        print(f"  Created: {txt_file_large.name} ({txt_file_large.stat().st_size/1024:.2f} KB)")

        # JSON file (10 KB)
        json_file = tmp_path / "test_10kb.json"
        create_test_json_file(json_file, size_kb=10)
        test_files.append(json_file)
        print(f"  Created: {json_file.name} ({json_file.stat().st_size/1024:.2f} KB)")

        # Benchmark Simple backend
        print(f"\n\n{'='*80}")
        print("Benchmarking Simple Backend")
        print(f"{'='*80}")

        simple_backend = registry.get(BackendType.SIMPLE)
        if simple_backend and simple_backend.available:
            results = benchmark_backend(simple_backend, test_files, iterations=3)
            print_benchmark_results(results)
        else:
            print("Simple backend not available")

    print(f"\n{'='*80}")
    print("Benchmark complete!")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
