<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;500;600;700;800&display=swap');

* { font-family: 'Montserrat', sans-serif !important; }
h1, h2, h3 { color: #2C3E50; border-bottom: 2px solid #0e4378; padding-bottom: 8px; display: block; }
code { font-family: 'Consolas', monospace !important; color: green; background-color: #f8f9fa; padding: 2px 4px; border-radius: 3px; }
.info-box { background-color: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 4px solid #0e4378; margin: 20px 0; }
</style>

# **Project Management Report**

## **1. Project Timeline & Milestones**
**Project:** NoCode_Bench  
**Start Date:** November 1, 2024  
**End Date:** January 31, 2025  
**Total Duration:** 90 Days  
**Key Milestone:** January 15, 2025 (Mid-Project Review)

| Date | Tasks |
| :--- | :--- |
| 2024.11.01 - 2024.11.10 | Project Initiation & Requirement Analysis |
| 2024.11.11 - 2024.11.20 | System Architecture & Design |
| 2024.11.21 - 2024.12.20 | Core Development - Backend & Frontend & Agent |
| 2024.12.21 - 2024.12.31 | Integration |
| 2025.01.01 - 2025.01.15 | Testing & Evaluation |
| 2025.01.16 - 2025.01.31 | Documentation & Deployment |

```mermaid
gantt
    title NoCode_Bench Project Timeline (Waterfall Model)
    dateFormat YYYY-MM-DD
    axisFormat %b %d

    section Phase 1: Planning
    Project Initiation & Requirement Analysis :done, p1, 2024-11-01, 2024-11-10
    System Architecture & Design              :done, p2, 2024-11-11, 2024-11-20

    section Phase 2: Development
    Core Development (Backend, Frontend, Agent) :active, d1, 2024-11-21, 2024-12-20
    Integration                                 :crit, d2, 2024-12-21, 2024-12-31

    section Phase 3: Testing & Deployment
    Testing & Evaluation                      :t1, 2025-01-01, 2025-01-15
    ★ Mid-Project Review                      :milestone, m1, 2025-01-15, 0d
    Documentation & Deployment                :t2, 2025-01-16, 2025-01-31
```

![Gantt Chart SVG](pics/gantt_chart_waterfall.svg)

## **2. System Architecture**
xxxx.
<p align="center"><img src="pics/architecture_diagram.png" width="90%"></p>

## **3. Method**
| Component | Choice | Rationale |
| :--- | :--- | :--- |
| design 1 | xxx | xxx. |
| design 2 | xxx| xxxx. |

## **3. Team Roles & Responsibilities**
| Name | Role | Key Contributions |
| :--- | :--- | :--- |
| **Kai-Hao, Yang** | Project Lead & AI Architect | Led the overall project direction and system design; architected and orchestrated agentic workflows across the platform. |
| **Hao Lin** | Backend & Evaluation Engineer | Test and engineered the automated evaluation pipeline. |
| **Han Hu** | Infrastructure & DevOps Engineer | Built Docker sandboxes and automated benchmark environment deployment. |
| **Kaihui, You** | Frontend & UI/UX Designer | Design and implement UI components and page layouts, Handle styling and responsive design. |
| **Hsuan Lien** | Frontend & API Integration Engineer | Integrate frontend with backend APIs, Handle routing, and error handling. |

## **4. Current Progress and Future Plans**
