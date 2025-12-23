This README file provides instructions on how to compile the project's Markdown documentation into high-quality PDF reports using the Markdown PDF extension in Visual Studio Code.

Documentation Compilation Guide
This repository contains the comprehensive project documentation for go42TUM, a real-time voice AI consultant for TUM applicants. The documentation is written in Markdown with embedded HTML/CSS to ensure a professional layout that aligns with the Technical University of Munich (TUM) corporate design.

# 1. Documentation Files
The following files are located in the docs/ directory:

cover.md: The report cover page, including team information and AI usage disclosures.

user_guide.md: Instructions for end-users on how to access and use the voice assistant.

project_management_report.md: Detailed technical overview, system architecture, and project timeline.

user_acceptance_testing.md: Results from user testing and framework evaluations.

Note: All images used in these reports are stored in the docs/pics/ folder.

# 2. Prerequisites
To compile these files into PDFs with the intended styling, you need the following:

Visual Studio Code (VS Code).

Markdown PDF Extension:

Open VS Code.

Go to the Extensions view (Ctrl+Shift+X).

Search for and install Markdown PDF (by yyzhang).

# 3. Compilation Steps
Follow these steps for each .md file in the docs/ folder:

- Step 1: Open the File
Open the desired Markdown file (e.g., user_guide.md) in Visual Studio Code.

- Step 2: Verify Image Paths
Ensure your folder structure remains intact. The Markdown files reference images using relative paths like pics/image_name.png.

- Step 3: Export to PDF
There are two ways to trigger the compilation:

    - Right-Click: Right-click anywhere inside the editor area of the Markdown file and select Markdown PDF: Export (pdf).

    - Command Palette: Press Ctrl+Shift+P (or Cmd+Shift+P on Mac), type "export", and select Markdown PDF: Export (pdf).

- Step 4: Locate Output
The extension will generate a .pdf file in the same directory as the source Markdown file.

4. Advanced Configuration (Optional)
The reports use custom <style> blocks for fonts (Montserrat) and colors. If the fonts do not render correctly in your local environment, ensure you have an active internet connection so the extension can fetch the Google Fonts linked in the files.

Common Troubleshooting
Page Breaks: The reports use <div style="page-break-after: always;"></div> to manage layout. The Markdown PDF extension respects these tags during export.

Missing Images: If images do not appear, verify that the pics/ folder is in the same directory as the .md file you are compiling.

**Feel free to change anything if needed!!!**