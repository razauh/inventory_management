import os

# Define the base directory to remove from paths
BASE_DIR = '/home/pc/Desktop/'
# Target directories to scan
TARGET_DIRS = [
    '/home/pc/Desktop/inventory_management/modules/customer/',
    '/home/pc/Desktop/inventory_management/modules/sales/',
    '/home/pc/Desktop/inventory_management/modules/purchase/',
    '/home/pc/Desktop/inventory_management/modules/vendor/'
]
# Output file name
OUTPUT_FILE = 'combined_code.txt'

def process_directory(directory, output_file):
    """Process all Python files in a directory and its subdirectories"""
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                # Get relative path starting from 'inventory_management'
                relative_path = os.path.relpath(file_path, BASE_DIR)
                
                # Read file content
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Write to output file
                output_file.write(f"{relative_path}\n")
                output_file.write("```\n")
                output_file.write(content)
                output_file.write("\n```\n\n")

def main():
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as out_f:
        for directory in TARGET_DIRS:
            if os.path.exists(directory):
                process_directory(directory, out_f)
            else:
                print(f"Warning: Directory not found - {directory}")
    
    print(f"Successfully created {OUTPUT_FILE} with all Python files")

if __name__ == "__main__":
    main()