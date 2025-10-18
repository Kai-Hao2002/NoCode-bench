import os
import json
import subprocess
import shutil
from django.core.management.base import BaseCommand
from django.conf import settings

class Command(BaseCommand):
    help = 'Automatically clones and checks out all required repositories from the NoCode-bench dataset.'

    def handle(self, *args, **kwargs):
        """
        Main handler for the command.
        """
        # --- Path Configuration ---
        test_file_path = os.path.join(settings.BASE_DIR, 'NoCode-bench_Verified', 'test', 'data.jsonl')
        codebases_root_path = os.path.join(settings.BASE_DIR, 'NoCode-bench_Verified', 'data')

        if not os.path.exists(test_file_path):
            self.stderr.write(self.style.ERROR(f"Test file not found: {test_file_path}"))
            return

        self.stdout.write(self.style.SUCCESS("Starting to set up all required codebases..."))
        self.stdout.write(self.style.WARNING("This may take a long time depending on your internet connection."))

        # --- Processing Logic ---
        repos_to_process = self.get_unique_repos(test_file_path)
        
        for repo_info in repos_to_process:
            repo_slug = repo_info['repo']  # e.g., "psf/requests"
            commit_hash = repo_info['base_commit']
            
            # Construct the target path (e.g., NoCode-bench_Verified/data/psf/requests)
            target_repo_path = os.path.join(codebases_root_path, *repo_slug.split('/'))
            
            # If the folder already exists, skip it to make the script re-runnable
            if os.path.exists(target_repo_path):
                self.stdout.write(f"Repository '{repo_slug}' already exists. Skipping.")
                continue

            # Ensure the parent directory exists (e.g., .../data/psf/)
            os.makedirs(os.path.dirname(target_repo_path), exist_ok=True)
            
            # Construct the GitHub URL
            git_url = f"https://github.com/{repo_slug}.git"
            
            self.stdout.write(self.style.SUCCESS(f"--- Processing: {repo_slug} ---"))
            
            try:
                # 1. Clone the project to the target path
                self.stdout.write(f"Cloning from {git_url}...")
                subprocess.run(
                    ['git', 'clone', git_url, target_repo_path],
                    check=True, capture_output=True, text=True
                )

                # 2. Checkout the specified commit
                self.stdout.write(f"Checking out commit {commit_hash[:8]}...")
                subprocess.run(
                    ['git', 'checkout', commit_hash],
                    cwd=target_repo_path,  # Run this command inside the cloned folder
                    check=True, capture_output=True, text=True
                )
                
                self.stdout.write(self.style.SUCCESS(f"Successfully set up '{repo_slug}'."))

            except FileNotFoundError:
                self.stderr.write(self.style.ERROR("`git` command not found. Please ensure Git is installed and in your system's PATH."))
                return
            except subprocess.CalledProcessError as e:
                self.stderr.write(self.style.ERROR(f"Failed to process '{repo_slug}'. Error: {e.stderr}"))
                # Clean up incomplete folder if clone fails
                if os.path.exists(target_repo_path):
                    shutil.rmtree(target_repo_path)
        
        self.stdout.write(self.style.SUCCESS("\nAll codebases have been set up successfully!"))

    def get_unique_repos(self, file_path):
        """
        Reads the data.jsonl file and returns a list of unique repositories and their base commits.
        """
        unique_repos = {}
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                data = json.loads(line)
                repo_name = data.get('repo')
                base_commit = data.get('base_commit')
                if repo_name and base_commit:
                    # Only store the first commit found, as base_commit should be the same for the same repo
                    if repo_name not in unique_repos:
                        unique_repos[repo_name] = {
                            "repo": repo_name,
                            "base_commit": base_commit
                        }
        return list(unique_repos.values())
