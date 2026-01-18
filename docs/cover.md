<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;500;600;700;800&display=swap');

* {
    font-family: 'Montserrat', sans-serif !important;
}

body, html {
    font-family: 'Montserrat', sans-serif !important;
    margin: 0;
    padding: 0;
}

.cover-page {
    min-height: 100vh;
    background: #ffffff;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    color: #2C3E50;
    padding: 20px;
    box-sizing: border-box;
}

.tum-logo {
    margin-bottom: 30px;
}

.report-title {
    font-size: 3.5em;
    font-weight: 800;
    margin-bottom: 20px;
    line-height: 1.2;
    color: #0e4378;
}

.report-subtitle {
    font-size: 1.8em;
    font-weight: 400;
    margin-bottom: 40px;
    opacity: 0.9;
    line-height: 1.4;
}

.team-section {
    background: #f8f9fa;
    border-radius: 15px;
    padding: 0 30px 30px 30px;
    margin: 30px 0;
    border: 1px solid #e9ecef;
    width: 85%;
    max-width: 900px;
}

.team-section h3 {
    font-size: 1.4em;
    font-weight: 600;
    margin-bottom: 20px;
    padding-top: 20px;
    color: #0e4378;
}

.team-members {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 15px;
    margin-top: 20px;
}

.team-member {
    background: #ffffff;
    padding: 15px;
    border-radius: 10px;
    text-align: center;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.team-member h4 {
    margin: 0;
    font-weight: 600;
    font-size: 1.0em;
    color: #2C3E50;
}

.university-info {
    margin-top: 50px;
    padding-top: 20px;
    border-top: 1px solid #e9ecef;
    opacity: 0.85;
    color: #2C3E50;
}

.university-info h4 {
    font-size: 1.3em;
    font-weight: 600;
    margin-bottom: 10px;
    color: #0e4378;
}

.university-info p {
    margin: 5px 0;
    font-size: 1.0em;
}

@media (max-width: 768px) {
    .report-title {
        font-size: 2.5em;
    }
    
    .report-subtitle {
        font-size: 1.4em;
    }

    .subtitle-small { 
        font-size: 14px; 
        font-weight: 300; 
        display: block; 
        margin-top: 5px; 
    }
    
    .team-members {
        grid-template-columns: repeat(2, 1fr);
    }
}

@media (max-width: 480px) {
    .team-members {
        grid-template-columns: 1fr;
    }
}
</style>

<div class="cover-page">
    <div class="tum-logo">
        <img src="pics/tum_logo.svg" alt="TUM Logo" width="120" height="120">
    </div>
    <h1 class="report-title">NoCode-bench</h1>
    <h2 class="report-subtitle"> <br><span class="subtitle-small"> An agent system that reads a documentation change and implements the corresponding code changes so that project tests pass. </span></h2>
    <div class="team-section">
        <h3>Group 7</h3>
        <div class="team-members">
            <div class="team-member">
                <h4>Kai-Hao Yang</h4>
            </div>
            <div class="team-member">
                <h4>Hao Lin</h4>
            </div>
            <div class="team-member">
                <h4>Han Hu</h4>
            </div>
            <div class="team-member">
                <h4>Kai-Hui You</h4>
            </div>
            <div class="team-member">
                <h4>Hsuan Lien</h4>
            </div>
            <!-- <div class="team-member">
                <h4>Member Name 6</h4>
            </div> -->
        </div>
    </div>
    <div class="university-info">
        <h4>Technical University of Munich (TUM)</h4>
        <p>School of Computation, Information and Technology</p>
        <p>Advanced Topics on Software Engineering (CITHN3003)</p>
        <p>Winter Semester 2025/2026</p>
        <p>January 20, 2026</p>
    </div>
</div>

<div class="cover-page" style="min-height: 100vh; justify-content: flex-start; padding-top: 60px;">
    <div style="max-width: 800px; text-align: left; color: #2C3E50;">
        <h1 style="font-size: 2.0em; font-weight: 600; color: #2C3E50; text-align: left; margin-bottom: 30px; border-bottom: 2px solid #0e4378; padding-bottom: 15px;">
            Acknowledgments of Generative AI Usage
        </h1>
        <div style="background: #f8f9fa; border-radius: 8px; padding: 20px; margin: 20px 0; border-left: 4px solid #0e4378;">
            <p style="font-style: italic; color: #0e4378; font-weight: 500; margin: 0; font-size: 1.1em;">
            In the development of this project, we have extensively utilized Generative AI tools to enhance our productivity and output quality.
            </p>
        </div>
        <p style="font-size: 1.0em; line-height: 1.6; margin-bottom: 20px;">
            The majority of our project content, including code, documentation, and design materials, has been generated with the assistance of AI tools. All AI-generated content has undergone thorough manual review and validation by our team members to ensure accuracy, quality, and compliance with project requirements.
        </p>
        <div style="margin: 25px 0;">
            <h3 style="font-family: 'Montserrat', sans-serif; font-weight: 600; color: #34495E; font-size: 1.2em; margin-bottom: 10px; border-bottom: 1px solid #BDC3C7; padding-bottom: 4px; display: block;">
                Code Development
            </h3>
            <p style="font-size: 1.0em; line-height: 1.6; margin-left: 0;">
            AI tools, including GitHub Copilot and ChatGPT, were utilized to assist in code generation, debugging, and optimization. Each code segment was reviewed and tested by team members to ensure functionality and adherence to coding standards.
            </p>
        </div>
        <div style="margin: 25px 0;">
            <h3 style="font-family: 'Montserrat', sans-serif; font-weight: 600; color: #34495E; font-size: 1.2em; margin-bottom: 10px; border-bottom: 1px solid #BDC3C7; padding-bottom: 4px; display: block;">
                Documentation
            </h3>
            <p style="font-size: 1.0em; line-height: 1.6; margin-left: 0;">
            AI-assisted writing tools helped in drafting technical documentation, user guides, and project reports. All documentation underwent comprehensive review and editing by team members to ensure clarity, accuracy, and consistency.
            </p>
        </div>
        <div style="margin: 25px 0;">
            <h3 style="font-family: 'Montserrat', sans-serif; font-weight: 600; color: #34495E; font-size: 1.2em; margin-bottom: 10px; border-bottom: 1px solid #BDC3C7; padding-bottom: 4px; display: block;">
                Quality Assurance
            </h3>
            <p style="font-size: 1.0em; line-height: 1.6; margin-left: 0;">
            While AI tools significantly accelerated our development process, we maintained strict quality control measures. Every AI-generated component was subject to individual team member validation and overall project integration testing to ensure cohesion and reliability.
            </p>
        </div>
        <div style="background: #f8f9fa; border-radius: 8px; padding: 20px; margin: 25px 0; border-left: 4px solid #0e4378; text-align: center;">
            <p style="font-style: italic; color: #2C3E50; margin: 0; font-size: 0.95em;">
                <strong>Meta-Disclosure:</strong> This "Acknowledgments of Generative AI Usage" section itself was generated using GenAI tools and subsequently reviewed and approved by our team to ensure accuracy and completeness of our AI usage disclosure.
            </p>
        </div>
    </div>
</div>