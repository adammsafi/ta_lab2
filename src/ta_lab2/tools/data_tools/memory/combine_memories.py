
import argparse
import json

def combine_jsonl_files(file_paths, output_path):
    """Combines multiple jsonl files into one."""
    unique_memories = set()
    count = 0
    with open(output_path, 'w', encoding='utf-8') as outfile:
        for file_path in file_paths:
            try:
                with open(file_path, 'r', encoding='utf-8') as infile:
                    for line in infile:
                        try:
                            # Use the content of the memory to determine uniqueness
                            memory = json.loads(line)
                            memory_content = memory.get("content", "")
                            if memory_content not in unique_memories:
                                unique_memories.add(memory_content)
                                outfile.write(line)
                                count += 1
                        except json.JSONDecodeError:
                            print(f"Warning: Skipping invalid JSON line in {file_path}: {line.strip()}")
            except FileNotFoundError:
                print(f"Warning: File not found, skipping: {file_path}")
    return count

def main():
    parser = argparse.ArgumentParser(description="Combine multiple .jsonl files into a single file, ensuring unique memories based on content.")
    parser.add_argument("output_file", help="The path to the output .jsonl file.")
    parser.add_argument("input_files", nargs='+', help="The paths to the input .jsonl files to be combined.")
    
    args = parser.parse_args()
    
    total_written = combine_jsonl_files(args.input_files, args.output_file)
    
    print(f"Successfully combined {len(args.input_files)} files into '{args.output_file}'.")
    print(f"Total unique memories written: {total_written}")

if __name__ == "__main__":
    main()
