# Prompt Orchestration Markup Language

Yuge Zhang, Nan Chen, Jiahang Xu, Yuqing Yang semantipy@microsoft.com Microsoft Research Shanghai, China

![](images/6dce33501a38c52e823f45b85f60d3707b5110fbe1ccf6a40c1bdc06bbc189cc.jpg)  
(1)  
(2)  
Figure 1: Developing the PomLink iOS prototype in VSCode – a case study of POML. (1) The development environment in <sup>46</sup>47VSCode, showcasing structured prompt authoring with POML: (a) prompt version control with Git; (b) a POML file example; (c) 49stylesheet definition for presentation control; (d) hover documentation for inline assistance; (e) inline diagnostics for error 51checking; (f) context-aware auto-completion; (g) the live preview panel displaying; (h) rendered embedded data (e.g., documents 53and tables). (2) An application prototype developed with POML that structures multimodal inputs for LLM analysis, supporting 55tasks such as (i) querying visual content and (j) summarizing documents based on rich context.

## Abstract

<sup>60</sup>Large Language Models (LLMs) require sophisticated prompting, <sup>62</sup>yet current practices face challenges in structure, data integra <sup>64</sup><sub>65</sub>tion, format sensitivity, and tooling. Existing methods lack com <sup>66</sup><sub>67</sub>prehensive solutions for organizing complex prompts involving <sup>68</sup><sub>69</sub>diverse data types (documents, tables, images) or managing presen <sub>71</sub>tation variations systematically. To address these gaps, we introduce <sup>72</sup><sub>73</sub>POML (Prompt Orchestration Markup Language). POML employs component-based markup for logical structure (roles, tasks, examples), specialized tags for seamless data integration, and a CSS-like styling system to decouple content from presentation, reducing formatting sensitivity. It includes templating for dynamic prompts and a comprehensive developer toolkit (IDE support, SDKs) to improve version control and collaboration. We validate POML through two case studies demonstrating its impact on complex application integration (PomLink) and accuracy performance (TableQA), as well as a user study assessing its efectiveness in real-world development scenarios.

## CCS Concepts

• Human-centered computing → Human computer interaction (HCI); Interaction design; • Software and its engineering → Markup languages; Formal language definitions; • Computing methodologies → Natural language processing.

## Keywords

Artifact or System, Machine Learning, Programming/Development Support, Prompt Engineering, Large Language Model

## 1 Introduction

Large Language Models (LLMs) have demonstrated remarkable ca pabilities across diverse tasks through carefully engineered prompts. These models, exemplified by the GPT series [14, 62], LLaMA [84], and others [22, 83], have shown proficiency in parsing and acting upon instructions in various domains. Their applications span code generation [17], question answering [37], mathematical reasoning [19], and interactive agents [78, 100]. As these applications grow in complexity, so too does the sophistication of prompting techniques used to elicit desired behaviors from LLMs. Advanced prompting strategies such as chain-of-thought [97], few-shot in-context learn ing [14], and ReAct (reasoning and acting) [101] have emerged as critical methods for improving model performance.

Within this evolving landscape, “structured prompting” [72, 95, 104] has gained prominence as a systematic approach to organizing instructions and context data within prompts. These structured approaches ofer numerous advantages: they componentize and standardize prompts for better automated editing [74], facilitate team collaboration [68], improve development eficiency [13], sup port fine-grained editing [24], enable reuse of proven designs [95], and potentially boost performance [44]. As LLM applications in creasingly integrate multiple data types – including images [83], tables [80], and documents [45], the need for a more organized approach to prompt design becomes increasingly apparent.

Despite these advances, prompt engineering faces four signif icant challenges that impede efective development and deployment of LLM applications. First, current practices lack standardized methods for the structured orchestration of prompts. Projects following “structured prompting” practices often involve scattered instructions, roles, tasks, and examples [95, 104], hindering main tenance and collaboration, especially in complex projects. Second, integrating diverse data sources remains complex. Large LLM applications increasingly require references to documents [45], ta bles [18, 103], or images [46]. Properly integrating and presenting these varied sources within prompts poses a significant engineering burden. Third, LLMs exhibit significant sensitivity to formatting and presentation [73, 76, 89]. Research has documented “butterfly efects,” where minor textual variations can dramatically alter results. The absence of a decoupled styling layer complicates system atic testing and refinement of prompt variations [48, 75]. Finally, prompt development and management sufer from inadequate tooling. Current workflows often lack efective version control and dif visibility [24], making tracking changes and collaboration dificult. Plain-text prompts are cumbersome to manage [11, 102], and limited IDE support hinders systematic improvement [9, 79].

Several existing approaches attempt to address these challenges, but each has its specific limitations. Workflow and agent orches tration tools like LangChain [3], Microsoft Guidance [53], and PromptChainer [98] manage multi-step flows but treat prompts as plain text or minimal templates, lacking structured data presen tation or advanced styling capabilities. Markup-based prompting approaches such as ChatML [77], MDXPrompt [30], PromptML [68], and VSCode PromptTSX [90] provide component-based frameworks but lack efective data handling, a well-separated styling system, or comprehensive development support. User interfaces for prompt comparison or logging exist [9, 57], yet lack the fundamental tools to author or structure prompts before running comparisons or evaluations.

To address these multifaceted challenges comprehensively, we introduce POML (Prompt Orchestration Markup Language). POML provides a novel paradigm designed to bring structure, maintainability, and versatility to advanced prompt engineering. POML is based on an HTML-like structured markup language featuring semantic components, such as <role>, <task>, and <example>, encouraging modular design and enhancing prompt reusability. To ease data integration, POML incorporates specialized data components (e.g., <document>, <table>, <img>) that seamlessly embed or reference external data sources like text files, spreadsheets, and images [18, 99]. These data components ofer customizable formatting options and eliminate error-prone manual text merging. To address format sensitivity, POML introduces a styling system inspired by CSS [26, 94]. This decouples content from presentation, allowing developers to modify styling (e.g., verbosity, syntax format) via separate <stylesheet> definitions (Figure 1 (c)) and systematically experiment with format variations without altering core logic. POML also includes a built-in templating engine for dynamically generating complex, data-driven prompts.

Beyond the language itself, POML addresses inadequate tooling with a comprehensive development toolkit. This includes an Integrated Development Environment (IDE) extension (initially for Visual Studio Code, see Figure 1 (1)) providing essential development aids like real-time previews (g), inline diagnostics (e), and auto-completion (f). The toolkit also provides Software Development Kits (SDKs) for seamless integration into Python and Node.js applications [3, 54]. Overall, the toolkit streamlines the prompt engineering lifecycle, enhancing authoring eficiency, debugging, version control (Figure 1 (a)), collaboration, and the systematic evolution of prompts.

We validate the efectiveness and utility of POML through rigorous empirical evaluation. This includes two distinct case studies and a formal user study. The first case study showcases POML’s practical application in building PomLink – an iOS agent application prototype (Figure 1 (2)). This study highlights how POML’s data components, styling, and tooling enabled the rapid development (a functional prototype in two days) of a complex application prototype requiring integration of documents, images, and tables. The second case study, focusing on Table Question Answering (TableQA), systematically explores the impact of prompt styling using POML’s styling system. It demonstrates that stylistic variations, easily managed by POML, can cause dramatic, model-specific diferences in LLM performance (e.g., accuracy improvements over 9x for some models) on table-based reasoning tasks [64]. Finally, our user study involving participants with varying expertise assessed POML’s usability across five representative tasks [20, 102]. The results confirmed POML’s efectiveness in structuring prompts and handling data, with participants particularly valuing the data components and development toolkits, while also providing constructive feedback for future enhancements.

The primary contributions of this work are:

(1) POML: A novel markup language designed specifically for prompt engineering, with specialized data components for effective integration of diverse data types, and a styling system for decoupling prompt content from presentation, enabling systematic control over formatting and mitigating LLM for mat sensitivity.

(2) An integrated suite of tools including an IDE extension with features like syntax highlighting, live preview, diagnostics, interactive testing, and multi-language SDKs to improve the development workflow, improve version control, and facili tate project management and collaboration.

(3) POML’s practical benefits and impact are empirically vali dated through two detailed case studies and a formal user study that assessed usability and efectiveness in realistic scenarios.

## 2 Related Works

## 2.1 Prompt Engineering and Structured Prompt

Large Language Models (LLMs) demonstrate remarkable capabili ties, yet their performance is highly sensitive to the input prompt’s quality and format [72]. This sensitivity is particularly pronounced when prompts involve complex data types such as tables, charts, or images, where carefully tuned presentation is often necessary for reliable results [18, 31, 36, 99, 103]. Indeed, research highlights a “butterfly efect,” where minor variations in phrasing, formatting, markup, or content order can dramatically alter LLM outputs and accuracy [35, 48, 73, 89, 106].

Consequently, prompt engineering – the practice of design ing inputs to optimize LLM outputs – has become essential [72]. Research has shown that enhancing prompts with in-context ex amples or iterative reasoning steps significantly improves results [14, 25, 96, 97, 101]. Within this field, structured prompting has emerged as a key practice, organizing prompts into standardized roles, tasks, or program-like formats [51, 66, 74, 95, 104]. Such approaches ofer advantages including improved reusability and maintainability [13, 24, 44, 68, 74, 95]. Conversely, unstructured prompts often impede team-based workflows, making targeted modifications dificult without afecting other prompt sections [24]. The lack of clear boundaries or standardized documentation for prompt segments (e.g., roles, tasks, examples) hinders the develop ment of shared tooling for parsing, manipulating, or reusing prompt components programmatically.

## 2.2 Prompt Development Challenges and Tooling

Studies on Prompt Usage and Challenges Studies on prompt usage patterns reveal significant challenges faced by users, especially non-experts. Minimalist web/chat UIs like OpenAI’s Playground and ChatGPT [59, 60] serve as short-term sandboxes, leav ing a gap between experimental prototyping and large-scale and production-ready prompt designs. In industry, trial-and-error approaches are common but hinder systematic improvements, as users often make erroneous assumptions about how to communicate with LLMs [20, 102]. This continuous editing process also makes prompt history tracking dificult, complicating version control and collabo ration. Text-based prompts frequently become opaque or dificult to manage over time [11, 24]. Tagging approaches are being explored to alleviate these issues by improving diferential comparisons and collaborative editing [68, 95], aligning with structured prompting practices.

Prompt Toolkits for Development and Evaluation Several integrated prompt toolkits have been developed to assist users in prompt engineering. Flow-based or multi-prompt systems provide pipelines for chaining multiple prompts with optional retrieval components in complex LLM applications [3, 53, 54, 98]. Other tools focus on prompt management and version control through standalone or web-based services [41, 65]. However, these systems typically manage the high-level orchestration of multiple steps or prompts, often treating individual prompts as opaque strings or simple templates, rather than providing detailed frameworks for structuring the content within a single complex prompt. POML can integrate with these systems as a specialized syntax for enhanced clarity and structure within individual prompt steps. Another stream of existing works is prompt evaluation interfaces, ofering UIs for comparing or perturbing prompts [4, 9, 57, 67, 79]. These are largely orthogonal to POML’s focus on prompt authoring and structure, and could potentially use POML’s declared sub-blocks for more fine-grained testing and analysis.

## 2.3 Web Frameworks and Prompt Markup Languages

Inspiration from Web Frameworks and Programming The evolution of web development ofers relevant parallels and insights for prompt engineering. Both domains share concerns around clarity, dynamic content, and adaptable layouts – whether for diferent screen sizes or context windows [49]. Principles like the separation ofstructure (HTML [12, 27]), presentation (CSS [26, 94]), and behavior (JavaScript [28]) have proven crucial for managing complexity in web development, providing a blueprint for prompt frameworks. Early dynamic websites relied on templating engines to map data into presentation views [29, 34, 40, 56, 85], akin to simple prompt templating in tools like LangChain [3] or Guidance [53]. A significant advancement came with component-based frameworks [5, 70, 91], which encapsulate structure, style, and logic into reusable units, enhancing modularity and maintainability [42, 81, 87, 88]. Building upon these frameworks, UI component libraries such as Ant Design [23] and MUI [58] provide extensive sets of pre-defined, high-level components (“widgets”) that further accelerate development by ofering ready-to-use solutions for common UI patterns, often including advanced data display capabilities. Languages like JSX [69], used extensively in React [70], exemplify this by allowing developers to define UI “components” using declarative, markup-like syntax combined with programming logic. This component-based approach improves code readability and fosters reuse. Conversely, manually constructing structured outputs via string concatenation is notoriously error-prone and hinders readability [15]. These lessons underscore the potential benefits of applying similar principles — using components, templates, and structured markup — to manage the complexity of modern prompt engineering, a core motivation for POML.

Prompting with Markup Languages Several markup-based or component-based prompt frameworks have emerged, though they vary in their approach and capabilities. Some approaches leverage JSX/TSX syntax within TypeScript (TS) for templating prompts [8, 10, 90]. These often prioritize adapting to context win dow lengths but may ofer limited built-in features for complex data input handling or advanced styling mechanisms. Other frameworks adopt broader React-inspired workflows or component models for orchestrating agent interactions or generating complex outputs [32, 33]. These systems typically ofer limited control over the fi nal prompt string’s styling or the embedding of diverse data types directly via markup. MDXPrompt [30] integrates MDX syntax for prompts but requires TypeScript API usage to render dynamic content, coupling the prompt definition to the execution environ ment. These approaches attempt to “componentize” prompts with HTML-like syntax but are limited in “widget-level” data input en capsulation, or focus primarily on high-level agent or workflow orchestration rather than providing comprehensive prompt-level structuring and styling solutions.

Outside the JS/TS ecosystem, other markup solutions propose structured tags but typically focus more on conversational chat formats or specialized formats for LLM training [13, 77]. PromptML [68], while advocating for a domain-specific language to improve standardization and collaboration, currently lacks integrated devel opment environment support, such as syntax highlighting, which can afect usability and adoption. SAMMO [75] operates at a higherlevel abstraction, representing prompts symbolically to allow for transformations and optimization searches. While these solutions provide intention-expressive tags or enable powerful symbolic ma nipulations, they generally lack built-in styling layers, flexible data import features across multiple formats, or comprehensive IDE toolkits. Many existing markup or programmatic approaches are also tightly bound to specific programming languages (e.g., Python), limiting flexibility. In contrast, POML aims to unify structured markup, efective data handling, decoupled styling, and integrated templating within a standalone language specification, supported by a comprehensive toolkit and SDKs for broader compatibility and ease of use across diferent development environments. A table summarizing the key diferences between POML and existing prompt markup languages is provided in Appendix A.

## 3 Motivations and Design Goals

## 3.1 Motivations

Insights gathered from preliminary discussions with 5 prompt en gineers in our research group highlighted 4 pressing challenges in contemporary prompt engineering. These challenges directly motivate our design of POML as a comprehensive solution for prompt development.

M1: Structured Prompt Orchestration Necessity While the benefits of structured prompting are increasingly recognized [13, 24, 44, 68, 74, 95], a significant problem lies in the lack of a stan dardized framework for implementation. Current practices often result in ad-hoc approaches using unstructured plain text where instructions, roles, tasks, and examples are scattered inconsistently throughout prompts [51, 95, 104]. This absence of standardization makes prompts dificult to maintain, optimize, and reuse, especially within collaborative development environments.

M2: Complexity in Data Integration Large LLM applications increasingly rely on varied data formats, requiring references to documents [45], tables [18, 103], or images [46]. Integrating these diverse data sources becomes chaotic and error-prone. Manual text shaping, multi-point editing, and frequent reformatting significantly hamper maintainability [24, 36]. Existing tools often rely on ad-hoc placeholders or separate scripts for data embedding [3, 11, 54], lacking efective, integrated solutions.

M3: Prompt Styling and Format Sensitivity LLMs exhibit significant sensitivity to subtle variations in input formatting, where minor presentational changes can drastically alter results [35, 73, 76, 89, 106]. This sensitivity underscores the need for structured control over prompt presentation. The absence of a mechanism to decouple presentation style from prompt content makes it dificult to systematically test, refine, or adapt prompt formats for diferent models or tasks [48, 75].

M4: Prompt Development and Management Challenges Current prompt development workflows sufer from poor dif visibility and version control [24], making it dificult to track changes and collaborate efectively. Existing prompt markup languages [13, 30, 68] often lack syntax highlighting, auto-completion, preview and debugging tools, increasing the learning curve and error rate. Many solutions [33, 90] are tightly bound to particular programming languages or frameworks, limiting their integration with existing development tools and workflows. These limitations hinder the eficiency of development and make prompt management increasingly dificult as projects scale.

## 3.2 Design Goals

Based on these motivations, we established four core design goals for POML, each intended to address one of the identified challenges. These goals focus on standardizing syntax, supporting efective data handling, separating styling from content, and providing developerfocused tooling.

DG1: Reusable and Maintainable Prompt Markup A primary goal is to provide a standardized, JSX-like markup language that inherently supports structured prompting practices (M1). The language should enhance prompt clarity and ensure that prompt logic is easily refactorable and shareable across projects or teams. It should support a hierarchical nesting structure to reflect logical relationships and improve flexibility. Furthermore, the system should ofer commonly used elements like roles, tasks, or few-shot examples, promoting modularity and consistency in line with structured prompting approaches [95, 104].

DG2: Comprehensive Data Handling To address the complexities of data integration (M2), the system should ofer efective and comprehensive data handling capabilities, including dynamic prompt generation. Specialized components should be provided to seamlessly embed commonly used static data sources into prompts, including documents, tables, and images [18, 45, 99]. These components should preserve important data details while ofering easy-touse interfaces for adjusting presentation formats (e.g., syntaxes for tables) [36], reducing the burden of manual text formatting. Fur thermore, the language itself should support integrated templating logic (variables, loops, conditionals) as most data are only available at the runtime. Support for fallback text for non-textual data should also be included to accommodate LLMs with varying multi-modal capabilities and enhance prompt robustness across models.

![](images/dc53a065b7b6933c0893a74cca8f9539cf90c8a2eeefc768fe8461970ea229e0.jpg)

DG3: Decoupled Presentation Specifications To manage LLM sensitivity to formatting (M3), a core design goal is to provide flexible control over prompt presentation while simultaneously decoupling these presentation specifications (styling) from the core prompt content. This separation should allow styling rules (e.g., bullet style, syntax format, verbosity) to be defined centrally with minimized modifications to prompt contents. The system should support format configurations at multiple levels (e.g., both overall syntax and local syntax) to adapt prompts easily to diferent LLM sensitivities or task requirements [35, 48]. This decoupling will ideally enable rapid testing and optimization while maintaining content integrity.

DG4: Enhanced Tooling for Development To address development and management challenges (M4), the framework must be accompanied by enhanced tooling. It should utilize standalone prompt files with a clear structure, facilitating integration with stan dard version control systems like Git and improving readability and collaborative editing. Dedicated IDE support should be provided with essential features like syntax highlighting, context-aware autocompletion, hover documentation, inline diagnostics, and a live preview. Finally, the system should maintain interoperability with popular LLM frameworks (e.g., LangChain [3] and Guidance [53]) through integration SDKs, allowing seamless integration into exist ing development workflows.

## 4 POML: Prompt Orchestration Markup Language

POML, standing for Prompt Orchestration Markup Language, introduces a novel structured paradigm designed for authoring, man aging, and testing prompts for LLMs. This section provides an overview of POML’s foundational elements, including its core syntax based on HTML principles, its features for integrating diverse data types, its styling system for formatting prompt content, and a templating engine for dynamic prompt generation. These features address common challenges in prompt engineering. POML’s hierarchical structure enhances clarity and reusability (DG1). Its data components streamline the integration of varied information sources (DG2). Its styling system manages LLM formatting sensi tivities (DG3). Its overall design combined with tooling (introduced in § 5) supports an enhanced development experience (DG4).

## 4.1 Structured Prompting Markup

The fundamental syntax of POML adopts an HTML-like structure, closely mirroring HTML conventions. This design choice stems from the observation that prompt engineering shares similarities with web design; both involve crafting interfaces — textual for LLMs, visual for humans — that require clear hierarchy, consistent presentation, and adaptability. Using an HTML-inspired approach also leverages developers’ familiarity with web technologies, reducing the learning curve [49]. Nested tags (called components in our case) form the overall structure, enabling the hierarchical composition of complex prompts from smaller, modular parts. Within these tags, attributes provide metadata or configure the behavior of individual components, similar to how attributes like src or href function in HTML. POML supports standard HTML comment syntax, <!– ... –>, allowing developers to embed annotations within the prompt source code without afecting rendering. POML also maintains compatibility with plain text, allowing for gradual adoption. The root <poml> tag is optional, akin to the optional <html> tag in web development, which minimizes overhead for simple prompts where only specific features like data embedding might initially be needed.

```html
<poml>
    <role>You are a data scientist.</role>
    <task>Tabular data visualization.</task>
    <stepwise-instructions>
    <list>
    <item>Determine the most suitable visualization(s).</item>
    <item>Visualize using matplotlib or seaborn.</item>
    </list>
    </stepwise-instructions>
    <output-format>
    The code should be wrapped in three backticks.
    </output-format>
    <example>
    <input><table src="path/to/example.csv" /></input>
    <output><code><doc src="code.py" /></code></output>
    </example>
    <table src="path/to/my/table.csv" />
</poml>
```  
Figure 2: An example illustrating POML’s structured markup and rendering (§ 4.1). Top: POML source code demonstrating core components: intention components (e.g., <role>, <task>, <example>), data components (e.g., <table>, <doc>), and basic structural components (e.g., <list>, <item>). Bottom: The corresponding rendered output, demonstrating how the structured markup translates into a clear prompt for an LLM. Note the rendering of intention components (e.g., <role> becomes the title “\*\*Role:\*\*”) and data components (e.g., the first <table> is rendered as Markdown from its CSV source).

Functionally, POML components fall into several key categories, conceptually similar to how complex user interface widgets are built upon fundamental HTML elements.

• Basic Structural Components provide fundamental text formatting and structural grouping capabilities, analogous to common HTML tags. Elements like <b> (bold), <i> (italic), <p> (paragraph), and <div> (division) allow for control over text presentation and logical grouping within larger content blocks, enhancing readability and structure. Alongside these static elements, POML includes components and syntax for dynamic content generation through its integrated templat ing engine, such as constructs for loops (for), conditionals (if), variable definition (<let>), and substitution ({{...}}). These templating features are detailed further in § 4.4.

• Intention Components define the core logic and overall structure of the prompt. These components implement the “structured prompting” paradigm [30, 51, 68, 95, 104], estab lishing the interaction’s purpose and guiding the LLM’s re sponse. Examples include the <role> component, used to define the persona the LLM should adopt; the <task> compo nent, which specifies the objective the LLM needs to achieve; and the <example> component, crucial for providing few shot demonstrations to guide the model’s behavior. Unlike data components, intention components organize the logical blocks of the prompt rather than presenting complex data directly. When rendered, components like <role> typically appear as formatted titles (e.g., \*\*Role:\*\*), with the presen tation adjustable via styling rules (§ 4.3). These intention components orchestrate the overall flow and content of the prompt, as illustrated in Figure 2.

• Data Components are designed to handle the integration of diverse external data formats into the prompt context. Elements such as <document>, <img>, and <table> provide methods to embed content from files or data structures. These components, detailed in § 4.2, are essential for grounding LLM responses in specific information or enabling tasks that operate on external data.

Rationale This hierarchical and descriptive markup enforces a logical organization, ofering significant advantages over unstructured plain text. For instance, as illustrated in Figure 2, the explicit separation of conceptual parts — using intention components like <role> and <task>, structuring instructions with <stepwise-instructions>, defining outputs with <output-format> and providing few-shot demonstrations [14] via <example> (which itself nests <input> containing data components like <table> and <output> referencing an external <doc>) — significantly improves prompt clarity and understandability, reducing ambiguity for both LLMs and human readers. These components, such as the tables shown integrated directly or within examples, can then be easily reused across diferent prompts or modified in isolation, fostering systematic prompt engineering (DG1). Compared to simpler for mats like PromptML [68], which primarily ofer basic task and exam ple definitions, POML provides richer semantic components crucial for handling diverse content types (DG2). Meanwhile, the modu larity allows individual components to be treated as self-contained units. Modifying components independently minimizes the risk of

unintended side efects elsewhere in the prompt, facilitating faster and safer iterations, supporting more agile development workflows. The combination of a standardized, text-based format and clearly named elements simplifies prompt management within standard version control systems like Git (Figure 1 (a)). This enhances collaboration, as changes become easier to track, merge, and discuss (DG4).

## 4.2 Data Components

POML provides specialized data components to systematically integrate diverse data modalities directly within the prompt structure, as exemplified in Figure 3. This capability directly addresses the critical need to combine LLM reasoning with varied external data sources, a key requirement for many advanced applications (DG2). POML’s modular data components reduce the inherent complexity associated with constructing prompts that incorporate multiple data inputs. These built-in components distinguish POML by ofering systematic handling for common data types within a unified framework, analogous to component libraries in modern UI frameworks [23, 58]. Currently, POML supports 7 distinct data components: document, table, folder, image, conversational messages, audio clip, web page. We detail 4 representative examples here; the remaining components operate similarly and are demonstrated in the case studies (§ 7).

Document The document component (Figure 3 (a)) provides a mechanism for referencing and embedding content from external text-based files, supporting formats like .txt, .docx, and .pdf. This is particularly crucial for tasks involving large amounts of background information or context, such as in retrieval-augmented generation (RAG) systems [16, 45]. It ofers granular control through attributes, allowing developers to specify character encoding, whether to preserve original formatting, whether to include or discard embedded images within documents like PDFs, and how to trim content — for instance, by selecting specific page ranges (e.g., selectedPages="1:3") — thereby helping manage the LLM’s limited context window.

Folder For scenarios involving interaction with file systems or code repositories, such as file system analysis, code reviews, and project navigation [39, 47, 86], the <folder> component (Figure 3 (b)) provides a structured way to represent directory hierarchies. It allows customization of the representation through attributes controlling the maximum depth of the displayed tree, filtering options to include or exclude files based on extensions or name patterns $( { \mathrm { e . g . , } } { \mathsf { f i l t e r } } { = } " \setminus ( ? ! _ { -- } ) . { \star } \setminus . { \mathsf { p y } } " )$ , and optional automatic summarization for very large directories to conserve context space. It can also display metadata like file sizes or modification dates and supports multiple output formats, including classic tree views using box-drawing characters, YAML, or JSON representations.

Table Tables are vital for complex question-answering over structured data [64], generating data visualizations [18], or performing data manipulation tasks [103]. The <table> component (Figure 3 (c)) supports a variety of input sources, including CSV, TSV, Excel spreadsheets, and JSON arrays of objects. Crucially, it allows specifying the output representation (e.g., Markdown, HTML, XML, plain CSV) and controlling content details such as the inclusion of

(c) Table Component Usage

![](images/148bcae1a59da73a56e82abdaf72e6c6889d3d1e424302cc1c5e163c360907ad.jpg)  
(d) Image Component Usage

Figure 3: Examples of POML data components demonstrating integration of diverse data types (§ 4.2). (a) <document> rendering selected PDF pages with multimedia; (b) <folder> displaying a filtered directory structure as YAML; (c) <table> extracting and formatting spreadsheet data as CSV; (d) <img> inserting a referenced image with resizing.

headers or indices, and selective presentation of rows or columns for large tables, ofering flexibility in presentation. Employing a consistent and well-defined table format via this component can sig nificantly enhance an LLM’s ability to accurately parse and reason over the tabular data, applicable to scenarios like [36, 80, 103].

Image Acknowledging the rapid advancement of multimodal LLMs capable of processing visual information [62, 83], POML in cludes the <img> component (Figure 3 (d)) for direct image insertion into prompts. Inspired by web accessibility principles [92–94], this component supports standard attributes like alt text, allowing prompts to be easily adapted to LLMs with varying capabilities, including those without vision, thereby enhancing robustness. Lay out can be influenced using a position attribute (e.g., before, after, here) to control placement relative to surrounding text. Attributes like maxWidth and maxHeight allow developers to suggest rendering constraints, potentially influencing the number of tokens consumed when sending image data to the model. Compared to interactive uploads in chat interfaces [21, 60] or less structured parameter passing in raw API calls [62, 83], inserting images via a dedicated component within the markup ofers superior program matic control and integration.

Extensions POML’s architecture is designed to be extensible. As LLMs evolve to handle new modalities, POML can incorporate additional data components for types like video segments and node edge graphs, maintaining a consistent framework for diverse data integration.

## 4.3 Styling System

A critical challenge in prompt engineering stems from the documented sensitivity of LLMs to subtle variations in input formatting [35, 73, 76, 89, 106]. Minor changes in presentation can significantly impact model performance, necessitating precise control over how prompt content is rendered (DG3). POML addresses this through a dedicated styling system designed to manage presentation efectively. The styling options provided, such as control over syntax formats, layout adjustments (e.g., chat vs. block formatting), list styles, and caption presentation, are informed by findings in prompt engineering research exploring these sensitivities [48, 76]. Inspired by the separation of concerns in web development (HTML for structure, CSS for style [26, 94]), POML deliberately decouples presentation rules from the core prompt content. POML ofers two primary mechanisms for applying styles: inline attributes and external stylesheets.

POML provides control over various presentation aspects known to influence LLM behavior, such as layout adjustments (e.g., chat versus block formatting), list styles (<list listStyle="decimal">), caption presentation (<hint caption="Important Note" captionStyle="header">), and overall verbosity [48, 76]. Beyond simple formatting, POML provides a crucial syntax attribute. This attribute allows developers to explicitly control the rendering format for specific components or the entire prompt (e.g., <table syntax="html"/> or <poml syntax="json">). This control is vital because diferent LLMs can exhibit varying sensitivities or capabilities when parsing structured formats like Markdown, JSON, or XML [7] embedded within the prompt text. The styling attributes can be nested, allowing, for example, a subsection of a predominantly Markdown-formatted prompt to be rendered as JSON, providing fine-grained control over the final string sent to the model. One way to apply these styling adjustments is via inline attributes on specific POML components — a convenient method for localized formatting familiar to web developers. Figure 4 ((b) compared to (a)) demonstrates how inline attributes can alter the presentation of <example> components.

![](images/0577a838357b54a84b4b928ec78948fa3d68d5bb25318837cc60a284c10101f0.jpg)  
Figure 4: Demonstrating POML styling capabilities (§ 4.3). (a) Default rendering of <example> components. (b) Inline chat and introducer attributes on the parent <examples> element modify its presentation (from chat messages to plain text with “\*\*Input\*\*”/“\*\*Output\*\*” captions). (c) A <stylesheet> applies global rules to POML in (a), controlling layout (chat=false), captions/prefixes (caption="Q:"/"A:"), and styles (captionStyle="plain"), resulting in customized output.

For managing styles more systematically across multiple compo nents or prompts, POML supports external stylesheets, typically defined in separate JSON files (e.g., stylesheet.json as shown in Figure 4 (c)). These files contain global formatting rules defined using a concise, JSON-like syntax. Style rules within the stylesheet target specific POML component types (e.g., hint, table) or userdefined classes (see § 7.2 for examples). Alternatively, these style rules can also be embedded directly within a POML document using the <stylesheet> tag, as shown in Figure 1 (c). Overall, stylesheets provide a mechanism to define styles that apply globally or to spe cific component types, ofering a way to batch-manage or customize styles that might otherwise be set inline individually. They ofer several advantages: (1) it provides centralized control, establishing a single source of truth for formatting; (2) it keeps the primary prompt logic cleaner by avoiding repetitive presentation attributes; (3) it simplifies style modifications by eliminating multi-point ed its, enhancing maintainability. As a result, this approach directly facilitates systematic experimentation with diferent presentation formats to address LLM sensitivities or task requirements (DG3) without altering the core prompt content.

## 4.4 Templating Engine

POML integrates a built-in templating engine to facilitate the cre ation of dynamic, data-driven prompts without execution environ ment dependencies (DG2). Inspired by established web templating systems [29, 34, 40, 69], this engine allows runtime customization without relying solely on external scripting. Key features include

![](images/c44ce6646de1b76155edf2287b1033d0e20b1ad41ce83dfe89a4f04f93c9757d.jpg)

Figure 5: Example of POML’s templating engine (§ 4.4): using <let> to load data (from files.json), for attribute to iterate over items, {{ ... }} for variable substitution (e.g., {{ file.name }}), and if/else attributes for conditional component rendering based on data values (embedding a <document> only if file.size is below a threshold)

variable substitution using {{variable}} syntax, iteration over data collections via the for attribute, conditional rendering using if/else-like attributes, and inline variable definition with the <let> tag. Figure 5 demonstrates these capabilities, showing how data loaded via <let> is iterated over with for, variables like {{ file.name }} are substituted, and component rendering is controlled conditionally based on file.size.

This integrated approach ofers advantages over manual string manipulation, which is often error-prone and hard to debug [15]. It reduces redundancy by enabling reusable prompt structures populated with varying data. The declarative nature enhances readability, providing a clearer view of the prompt structure. Furthermore, the engine is independent from other programming languages, diferentiating POML from other solutions relying on existing templating engines (e.g., [3]), contributing to a cohesive framework where 31structure, presentation, data integration, and dynamic logic are managed within a single language. Details on the templating en 34gine’s syntax and capabilities are available in Appendix B.

![](images/ad6765f2351b8876af869db8dadfcf4c0d2a55f46e996a8856391e0015059805.jpg)  
<sup>1</sup>9Figure 6: Real-time diagnostic feedback from the POML toolkit in the IDE. (a) Errors indicated directly in the editor 22via inline highlighting (e.g., missing attribute). (b) Hovering <sup>23</sup>over an error shows detailed validation messages and doc-<sub>25</sub>umentation. (c) A dedicated panel lists all detected issues 26(syntax errors, validation problems, file processing issues).

## <sup>36</sup>5 Development Toolkit

<sup>38</sup>Complementing the core POML language specification, a compre hensive development toolkit is provided to enhance the eficiency, 41reliability, and collaborative nature of the prompt engineering pro <sup>42</sup>cess, directly addressing (DG4). While POML’s architecture allows 44potential integration with specialized prompt engineering environ <sup>45</sup>ments like PromptIDE [79] or ChainForge [9], our initial imple mentation focuses on providing a feature-rich experience within 48Visual Studio Code, a widely adopted and familiar IDE. This toolkit encompasses two key aspects: (1) integrated POML IntelliSense 51for rapid issue detection and code authoring assistance, and (2) <sup>52</sup>Software Development Kits (SDKs) enabling integration of POML into established software development ecosystems.

## <sup>56</sup>5.1 POML IntelliSense

58POML IntelliSense refers to a suite of integrated features designed <sup>59</sup>to simplify the prompt authoring process within the IDE, providing 61real-time feedback and assistance.

63Syntax Highlighting Syntax highlighting, adapted from stan-<sup>64</sup>dard HTML conventions due to POML’s similar structure, visually <sub>66</sub>diferentiates component tags, attributes, and content. This im-<sup>67</sup>proves code readability and aids in identifying structural elements.

<sup>69</sup>Hover and Auto Completion Informative hover tooltips and context-aware auto-completion enhance productivity. Hovering 72over POML elements displays dynamically retrieved documenta <sup>73</sup>tion, definitions, and examples (Figure 6 (b); Figure 1 (d)), ensuring 75up-to-date information. As the developer types, the system pro <sup>76</sup>vides context-aware auto-completion suggestions (Figure 1 (f)). It intelligently suggests valid POML component names based on the <sup>47</sup><sub>48</sub>current nesting context, available attributes for a given compo-<sup>49</sup>nent, and permissible values for certain attributes (e.g., predefined 51style options), reducing errors and accelerating development by 53facilitating syntax discovery.

![](images/39083c9c3befe2eb60362ec5433b498dff8392178e6c7dc7cac9f700d099dc78.jpg)  
31Figure 7: Integrated interactive prompt testing within the 33POML development environment. (a) Users initiate or <sub>35</sub>abort tests against specific model types (e.g., chat or text-<sup>36</sup>completion) via a context menu directly from the editor. (b) <sup>38</sup>The live preview panel displays the prompt being tested. (c) <sup>40</sup>The output panel shows test progress logs and streams the 42LLM’s response in real-time.

56Inline Diagnostics Real-time inline diagnostics provide imme-58diate feedback within the editor (Figure 6; Figure 1 (e)). Potential 60syntax errors, invalid attributes, or structural issues are automatically detected and highlighted with descriptive messages attached <sup>63</sup>to the problematic lines for rapid identification and correction. The <sup>65</sup>system employs error tolerance, attempting to recover from de-<sup>6</sup>7tected issues and reporting multiple issues simultaneously (Figure 6 69(c)), allowing developers to address several problems eficiently.

72Live Preview Working in concert with inline error reporting 74is a dynamic live preview feature (Figure 7 (b); Figure 1 (g)). This 76feature renders a visual representation of the final prompt structure <sub>78</sub>as the POML code is being written, updating automatically with <sup>79</sup>each change. This immediate visual feedback helps verify com <sup>81</sup>ponent hierarchy, content, styling, and templating, reducing the <sup>83</sup>cognitive load [8] of mentally translating markup. The preview 85mechanism supports multiple viewing modes tailored to diferent 87needs: a “speaker mode” for chat-based LLMs, a “text mode” for <sub>89</sub>text completion models, a visually enhanced “render mode” for <sup>90</sup>readability, and a “plain text mode” showing the exact raw string <sup>92</sup>for debugging subtle spacing issues.

<sup>95</sup>Interactive Testing Integrated interactive testing allows devel-<sup>97</sup>opers to initiate LLM tests directly within the editor (Figure 7). <sup>99</sup>Users can select model types (e.g., chat, text-completion) via a context menu (Figure 7 (a)) and test the current prompt without context switching. The output panel (Figure 7 (c)) displays test progress logs and streams the LLM’s response in real-time, enabling immediate observation and early abortion of the generation in case it starts to deviate from the desired outcome (Figure 7 (a)). This tight feedback loop facilitates iterative refinement and assessment of prompt compatibility across LLMs, addressing model sensitivities (DG3) and accelerating the write-debug-validate cycle.

```javascript
import { poml } from "poml";
const data = readPopulationData();
const prompt = <Text>
    <Task captionStyle="bold">
    Forecast the population in 2050.
    </Task>
    <Table syntax="csv" records={data} />
</Text>
const messages = await poml(prompt);
const response = await invokeLm(messages);
```

```python
import poml
data = open("globalwarming.pdf", "rb").read()
prompt = poml.Prompt()
with prompt:
    with prompt.task():
    prompt.text("Will 2025 be the warmest year?")
    prompt.document(buffer=data)
    messages = prompt.render()
    response = openai.chat.completions.create(messages)
(b) Python SDK Example Usage
```  
Figure 8: Using POML Software Development Kits (SDKs) to integrate into programming workflows. (a) JavaScript/TypeScript SDK example using JSX-like tagged template literals. (b) Python SDK example using a context manager approach.

LSP Server The IntelliSense features described above — includ ing hover information, auto-completion, and inline diagnostics — are powered by a dedicated implementation of the Language Server Protocol (LSP) [52]. Leveraging the standardized LSP allows these rich language-specific capabilities to be provided consistently. Caching and throttling are implemented at the side of LSP server, ensuring that the client (e.g., VSCode) remains responsive and does not experience performance degradation during heavy usage. This architectural choice not only enhances the development experience currently within VSCode but also creates the potential for integrating POML IntelliSense into other LSP-compatible editors (e.g., Emacs, PyCharm) in the future.

## 5.2 Node.js and Python SDKs

To facilitate integration into larger software applications, POML provides Software Development Kits (SDKs) for the Node.js (JavaScript / TypeScript) and Python environments, chosen for their prevalence in web development and AI respectively (Figure 8).

The Node.js SDK (Figure 8 (a)) allows programmatic POML definition using familiar JavaScript paradigms like JSX syntax or React-style functional components [33, 90]. This approach supports creating typed, composable prompt components that can be versioned and shared using standard tools like npm. It also enables developers to define custom, extensible POML components using

TypeScript or JavaScript, allowing the core language to be augmented within specific application contexts.

Similarly, the Python SDK (Figure 8 (b)) ofers an idiomatic interface using context managers and a fluent API builder pattern, inspired by libraries like yattag [43]. This design facilitates integration into Python-based AI/ML workflows, for instance, dynamically creating prompts within data processing pipelines or interacting with frameworks like LangChain [3]. Importantly, the Python tooling also supports a standalone mode, allowing direct processing of .poml files via scripts or command-line tools, ideal for rapid testing as demonstrated in our TableQA case study (§ 7.2).

Crucially, both SDKs support programmatic generation and manipulation of stylesheets. This capability enables advanced use cases, such as the automated exploration and optimization of prompt styles. They are also compatible with popular LLM client libraries, simplifying the integration of POML-generated prompts into the LLM communication layer. Furthermore, the language-agnostic design of the core POML specification also allows for the potential development of SDKs in other languages (e.g., C#, Java, Go) in the future.

## 6 Implementation

Core Technology Stack The core POML engine is developed using TypeScript, leveraging the React framework combined with Server-Side Rendering (SSR) [71]. React’s component model naturally supports POML’s design philosophy centered on separable and reusable prompt components. SSR facilitates the eficient handling of asynchronous operations, such as processing external data sources like images or documents referenced within prompts.

Codebase Overview The POML codebase currently comprises approximately 14.8k lines of TypeScript code. This implementation realizes the POML language specification, encompassing 37 distinct components (categorized into 14 basic structural, 7 data, 11 intention, and 5 utility components) and a total of 283 attributes. The codebase is divided into approximately 11.3k lines for the core engine functionality, 3.4k lines for the Visual Studio Code extension features (§ 5.1), and 96 lines for a lightweight Python SDK wrapper (§ 5.2). Comprehensive testing validates the implementation through 10 test suites containing 115 distinct test cases. These tests cover diverse scenarios, including basic tag parsing, attribute validation, complex multi-modal data integration, nested component structures, and the correct application of styling rules, verifying robustness of core POML features.

Rendering Architecture The POML implementation employs a three-pass rendering architecture to enhance modularity and extensibility. First, a Parser pass validates the input POML markup, executes templating logic (loops, conditionals), resolves variables, applies styles, and transforms the source code into React JSX components. Second, React processes these components, and generates a comprehensive Intermediate Representation (IR). This IR is a structured tree containing the resolved content, computed styles, and associated metadata. Third, a dedicated Writer pass traverses the IR and serializes it into the final target output format (e.g., Markdown, JSON, plain text). This separation of concerns significantly enhances flexibility; for instance, it enables support for new output formats by implementing additional Writers without modi fying the core parsing or IR generation stages. Furthermore, this architecture potentially allows support for alternative input syn taxes beyond XML, such as Markdown extensions or YAML, by developing corresponding Parser modules. It also facilitates perfor mance optimizations like IR caching. A detailed explanation of the rendering architecture is available in Appendix C.

![](images/7c764562f934833ceb040c633870c9b324592b2df08d629ebef203aa50cc382d.jpg)  
(1)

![](images/3f6597125dedd4fc255ef9bf8655bc227f9945f732d524cd6288419128172135.jpg)  
(2)  
Figure 9: PomLink iOS interface, powered by POML. (1) Main chat screen showing LLM interaction: (a) linked Excel data within the conversation; (b) buttons for adding various file types. (2) Table configuration panel, derived from POML’s <table> component features, where users can select (c) documents/tables, configure (d) inclusion options (e.g., file name), and choose (e) table formatting preferences (including an “Auto” option)

## 7 Case Studies

## 7.1 PomLink – Prototype of iOS Agent

To demonstrate POML’s utility in developing complex, data-intensive applications, we created PomLink, an iOS agent prototype. This case study highlights POML’s capability to streamline the integration of diverse data sources within a functional LLM-powered mobile ap plication. PomLink functions as an LLM agent that utilizes context derived from “linked” files, which users can upload via dedicated interface buttons supporting various types including documents, ta bles, images, webpages, and voice memos (Figure 9 (1)), all of which can be tailored to personalized settings. For example, tapping the “Files” button (Figure 9 (b)) initiates a pop-up window, asking the user to select multiple documents or tables from the file system (Figure 9 (c)), with an optionally adjusted inclusion style, which are then linked to the agent’s session. Once files are linked, users can have a conversation with the agent (Figure 1 (2); Figure 9 (1)). This interface enables both customized “ask anything” queries and the use of predefined task shortcuts like “Translate”, “Summarize”, “Rewrite”, and “Brainstorm”. These shortcuts operate on the context provided by both the linked files and the rich multi-modal chat history. The primary objectives of this case study were twofold: first, to validate POML’s efectiveness by integrating it into a functional mobile application prototype; and second, to assess how POML’s features aided the development process, particularly in handling diverse data inputs and managing prompt complexity within this application.

PomLink’s core agent functionality relies extensively on POML for structuring the prompts used to interact with LLMs. This structure incorporated several key POML features, visible in the example prompt within the development environment shown in Figure 1 (b). Specifically, we used:

• An <include> component to modularly incorporate a common system prompt stored in a separate file, enhancing reusability and maintainability.

• The <conversation> component to present the conversational history between the user and the agent systematically, crucial for maintaining context in interactive sessions.

• Components like <role>, <task>, and <output-format> to provide a clear structure based on the RTF prompting framework [104], organizing instructions for both the LLM and human developers.

• Various data components (§ 4.2) to integrate content from the linked files selected by the user.

• The styling system (§ 4.3) to define formatting rules centrally and create distinct style profiles (e.g., compact vs. verbose), allowing adaptation to specific tasks or backend LLMs.

Integrating varied data sources into the prompt context is a key challenge in developing applications like PomLink. POML addresses this by providing components to reference diverse data types structurally and the flexibility to specify their processing and presentation to the LLM. For instance, the <document> component was used to embed content from user-selected text document files (e.g., PDF documents). Attributes within this component allowed control over details like page selection or whether to preserve original formatting and embedded images. Similarly, the <table> component ingested data from table files (e.g., Excel or CSV). This component allowed specifying input formats and ensured consistent rendering of table data (e.g., as Markdown or CSV) within the prompt. Figure 9 (2) displays the user-facing options derived directly from POML’s <table> component capabilities for customizing data processing, such as toggling file name inclusion (Figure 9 (d)), incorporating column descriptions, selecting rendering formats, and choosing between full or partial table rendering. Notably, the “Auto” table format option (Figure 9 (e)) leverages findings from our TableQA study (§ 7.2) to automatically select the empirically determined best format for the target LLM. Representing other data types like voice memos (<audio>), web pages (<webpage>), images (<img>), or managing conversation history (<conversation>) was achieved straightforwardly using POML’s unified framework for context data aggregation.

PomLink was implemented using the React Native framework, a popular choice for cross-platform mobile application development. The development process for PomLink highlighted POML’s value for rapid prototyping. A functional prototype was completed by one ofthe POML developmentteam injust2days. Around 90% ofthis time was dedicated to iOS environment configuration, UI development, and simulator deployment, rather than core prompt engineering tasks. The application’s core logic required only 6 POML prompts: 1 common system prompt, 4 task-specific prompts, and 1 prompt pro cessing “ask-anything” queries, averaging a concise 35 lines of code each. This eficiency stems from POML’s ability to abstract complex data handling. The built-in data components managed file parsing and formatting, eliminating the need for custom data processing code typically required in traditional approaches. This allowed the developer to focus primarily on the application’s logic and user interface. Furthermore, prompt styling was managed efectively through POML’s internal styling system; presentation adjustments (e.g., captions, spacing, syntax) were made eficiently by modifying the central stylesheet JSON (Figure 1 (c)), without altering the main prompt logic.

The development workflow for PomLink was significantly accel erated by POML’s toolkit (§ 5), particularly the VSCode extension. Within the PomLink project, the extension’s live preview (Figure 1 (g)) provided immediate visual feedback on prompt rendering, in cluding embedded document files (Figure 1 (h)), while integrated diagnostics (Figure 1 (e)) instantly flagged errors, streamlining de bugging. Hover documentation (Figure 1 (d)) and auto-completion (Figure 1 (f)) reduced the need to consult external references. The interactive testing feature (Figure 7) allowed rapid iteration by en abling direct LLM calls and response viewing within the editor, considerably shortening the debug cycle for PomLink’s prompts. Integration into the PomLink application’s React Native backend was achieved using the POML Node.js SDK (Figure 8 (a)), which handled loading POML files, injecting dynamic data, and rendering the final prompt string. The text-based, modular nature of POML prompts also integrated seamlessly with Git for version control within the project (Figure 1 (a)).

In summary, the PomLink case study validated POML’s efectiveness as a practical tool for real-world LLM application development. It demonstrated how POML’s features streamline development: its structural markup (DG1), its data components (DG2), styling system (DG3), and development toolkit (DG4) collectively enabled rapid prototyping and simplified the management of complex, multimodal prompts. The ability to create a versatile agent application prototype in just two days highlights POML’s potential to accelerate innovation in developing sophisticated LLM-powered software by managing prompt structure and integration complexities efec tively.

## 7.2 TableQA – Deep Exploration of Prompt Styling

Prior research indicates that the specific structure and format used to present information within a prompt can significantly influence LLM performance [73, 76, 89]. However, systematically exploring this styling aspect is challenging due to the combinatorial com plexity of generating prompt variants. This case study investigates the impact of prompt styling on LLM performance for the task of table-based question answering (TableQA). Our primary goals were twofold: first, to quantify the sensitivity of diferent LLMs to stylistic variations in prompts, and second, to demonstrate how POML’s features, particularly its styling system, facilitate systematic management and exploration of these prompt styles.

![](images/2deaf150b1954add320e265df0f13d9487b372d919c45c51926473de69545701.jpg)  
Figure 10: Visualization of the prompt styling search space explored in our TableQA experiment. The diagram illustrates the dimensions of prompt variation investigated, including overall syntax structure (a), section formatting options (b, d), example presentation styles (c), and table representation alternatives (e). Systematically combining these choices resulted in an extensive search space of 74k unique prompt styles.

To conduct this investigation, we leveraged POML’s separation of content (markup) and presentation (stylesheets). We authored a single base POML prompt defining the TableQA task structure, including intention components, few-shot examples, and placehold ers for the question and table data (provided in Appendix E). We then defined a set of stylistic variations within POML stylesheets (example also available in Appendix E). These stylesheets controlled elements like the overall prompt syntax (e.g., Markdown, JSON, XML), the rendering format ofembedded table data (e.g., CSV, Mark down, HTML), the presentation style of instructions and examples (e.g., caption styles, visibility, chat formatting), and the structure of the question-answer section, as visualized in Figure 10.

Table 1: Optimal prompt styling configurations that yielded the highest accuracy for each LLM on the WikiTQ subset. Shows the specific combination of syntax and formatting choices (e.g., Overall Syntax (Figure 10 (a)), Example Body format (Figure 10 (c)), Table Syntax (Figure 10 (e))) for the best-performing style among 100 sampled styles.

<table><tr><td>Model</td><td>Overall Syntax</td><td>Table Syntax</td><td>Instruction Header</td><td>Example Caption</td><td>Example Body</td><td>QA Caption</td><td>QA Body</td><td>User Input Caption</td></tr><tr><td>Claude 3 Haiku</td><td>XML</td><td>HTML (Ugly)</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr><tr><td>DeepSeek V3</td><td>Markdown</td><td>HTML</td><td>Plain-Upper</td><td>Hidden</td><td>Hidden</td><td>Bold-Colon</td><td>Question-Answer</td><td>Hidden</td></tr><tr><td>Gemini 2.0 Flash</td><td>HTML</td><td>HTML</td><td>Header-Upper</td><td>Hidden</td><td>Introducer</td><td>Bold-Colon</td><td>Q-A</td><td>Header-Upper</td></tr><tr><td>GPT-3.5 Turbo</td><td>Markdown</td><td>TSV</td><td>Plain-Upper-Colon</td><td>Header</td><td>Hidden</td><td>Hidden</td><td>Hidden</td><td>Hidden</td></tr><tr><td>GPT-4o Mini</td><td>Markdown</td><td>Markdown</td><td>Plain-Upper</td><td>Header</td><td>Hidden</td><td>Bold-Colon</td><td>Question-Answer</td><td>Plain-Upper</td></tr><tr><td>LLaMA 3 70B</td><td>Markdown</td><td>Markdown</td><td>Header-Colon</td><td>Header-Colon</td><td>Chat w. Introducer</td><td>Header-Colon</td><td>Question-Explanation</td><td>Header-Colon</td></tr><tr><td>Mistral AI 8x7B</td><td>Markdown</td><td>XML</td><td>Bold-Upper-Colon</td><td>Bold-Upper-Colon</td><td>Chat</td><td>Bold-Colon</td><td>Question-Answer</td><td>Bold-Upper-Colon</td></tr><tr><td>Phi-3 Medium</td><td>JSON</td><td>CSV</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr></table>

Table 2: Impact of prompt styling variations on LLM accuracy for TableQA (WikiTQ subset). Shows minimum/maximum accuracy across 100 sampled styles, performance diference (Dif), relative improvement ((Max-Min)/Min), and style rank ing stability (Self-correlation: mean Spearman correlation of style rankings across 1000 random data splits, see Figure 14).

<table><tr><td>Model</td><td>Acc Min</td><td>Acc Max</td><td>Diff</td><td>Self-corr.</td></tr><tr><td>Claude 3 Haiku</td><td>0.138</td><td>0.555</td><td>0.417 (+303%)</td><td>0.866</td></tr><tr><td>DeepSeek V3</td><td>0.682</td><td>0.823</td><td>0.141 (+21%)</td><td>0.348</td></tr><tr><td>Gemini 2.0 Flash</td><td>0.717</td><td>0.830</td><td>0.113 (+16%)</td><td>0.314</td></tr><tr><td>GPT-3.5 Turbo</td><td>0.060</td><td>0.618</td><td>0.558 (+929%)</td><td>0.767</td></tr><tr><td>GPT-4o Mini</td><td>0.622</td><td>0.753</td><td>0.131 (+21%)</td><td>0.473</td></tr><tr><td>LLaMA 3 70B</td><td>0.152</td><td>0.657</td><td>0.505 (+333%)</td><td>0.606</td></tr><tr><td>Mistral AI 8x7B</td><td>0.177</td><td>0.481</td><td>0.304 (+172%)</td><td>0.849</td></tr><tr><td>Phi-3 Medium</td><td>0.007</td><td>0.322</td><td>0.314 (+4450%)</td><td>0.931</td></tr></table>

From this extensive space, we randomly sampled 100 styles with out replacement for evaluation. These 100 distinct prompt styles were tested on 283 samples (10% of the data) from the WikiTable-Questions (WikiTQ) validation dataset [64]. Accuracy was measured by comparing the LLM’s generated answer and the ground truth answer with evaluation tools provided by WikiTQ. The evalu ation included 8 low-cost LLMs (priced under \$0.3 per million input tokens as of February 2025): Claude-3-Haiku [6], DeepSeek-V3 [22], Gemini-2.0-flash [21], GPT-3.5-turbo-0125 [61], GPT-4o-mini [63], LLaMA3-70B [84], Mistral-AI-8x7b [38], and Phi3-medium [55].

Results The experimental results confirmed a significant depen dency between prompt styling and TableQA accuracy, as detailed in Table 2. The degree of sensitivity to styling, however, varied considerably across models. Some models were extremely sensitive: GPT-3.5-Turbo’s accuracy ranged from 6% to 61.8%, a relative improvement of 929%, while Phi-3 Medium improved by 4450% (from 0.7% to 32.2% accuracy) between its worst and best styles. Other models, such as DeepSeek V3 and Gemini 2.0 Flash, were less sensitive, with performance varying by 21% and 16% respectively, highlighting model-dependent sensitivity. The self-correlation scores in Table 2 (especially 0.931 for Phi-3 Medium, 0.866 for Claude 3 Haiku) suggest that the relative performance ranking of diferent styles is stable for many models across diferent data subsets. Our further analysis revealed that the optimal prompt style is model-specific. Table 1 details the combination of styling features (e.g., overall syntax, table syntax, example formatting) that yielded the best performance for each model. This model-specific optimal styling highlights the challenge of prompt portability and the need for adaptable styling mechanisms. Overall, this TableQA case study underscores the critical role of prompt styling in achieving optimal LLM performance, which POML addresses.

Table 3: Table format preferences across LLMs for the TableQA task. For each model, the table shows the top two preferred table syntax formats (e.g., CSV, Markdown, HTML) based on the highest average exact match accuracy achieved by prompt styles utilizing that specific format within our sample of 100 styles. The corresponding mean accuracy for each format is shown in parentheses.

<table><tr><td>Model</td><td>Best Format</td><td>Second Best Format</td></tr><tr><td>Claude 3 Haiku</td><td>CSV (0.449)</td><td>Markdown (0.424)</td></tr><tr><td>DeepSeek V3</td><td>HTML (0.801)</td><td>JSON (0.800)</td></tr><tr><td>Gemini 2.0 Flash</td><td>XML (0.791)</td><td>HTML (0.788)</td></tr><tr><td>GPT-3.5 Turbo</td><td>Markdown (Collapse) (0.524)</td><td>CSV (0.510)</td></tr><tr><td>GPT-4o Mini</td><td>JSON (0.702)</td><td>Markdown (0.694)</td></tr><tr><td>LLaMA 3 70B</td><td>Markdown (0.601)</td><td>HTML (0.601)</td></tr><tr><td>Mistral AI 8x7B</td><td>XML (0.365)</td><td>HTML (Ugly) (0.348)</td></tr><tr><td>Phi-3 Medium</td><td>CSV (0.169)</td><td>JSON (0.116)</td></tr></table>

A critical styling dimension for TableQA is the format used to represent the table data itself. Our results, summarized in Table 3, reveal diversity in the optimal table formats across diferent models, consistent with previous findings [36, 103]. While some models performed best with simple formats like CSV, others preferred structured representations like HTML, XML, JSON, or Markdown variants. This variation emphasizes the importance of tailoring table representations to the target LLM for optimal performance. These findings directly informed the development of our PomLink application (§ 7.1). The “Auto” table format option within PomLink uses these results, automatically selecting the table syntax identified as optimal for the user’s chosen backend LLM based on this study.

On the other hand, the experiment demonstrates the value of POML’s design, especially the separation of content (markup) from presentation (stylesheets) (DG3). This study required only one sin gle, concise base POML prompt (30 lines of code, see Appendix E). By programmatically combining stylesheet variations, we generated a combinatorial search space encompassing 73,926 unique prompt style configurations derived from the single base POML file. Using the POML Python SDK (§ 5.2), we loaded the base “.poml” file and rendered final prompts by combining it with the generated stylesheets and the specific table/question data for each test case. By enabling systematic variation and optimization of styling parameters independently of the core prompt logic, POML provides a mechanism for adapting prompts to diferent LLM characteristics and maximizing performance through experimentation, reducing the engineering efort compared to manually managing numerous prompt variations.

## 8 User Study

We conducted a formal user study to evaluate the usability, efectiveness, and developer experience of POML and its toolkit in practical scenarios. The study aimed to assess POML’s utility for representative prompt engineering tasks and gather qualitative feedback to identify its strengths and limitations.

Participants We recruited seven participants with diverse techni cal backgrounds, including software engineers, researchers, and stu dents. Participants had no prior exposure to POML or its use cases before the study. Participant backgrounds, self-reported prompt engineering experience levels, and prior use of LLMs in application development are detailed in Table 4. This diversity was sought to gather feedback reflecting diferent potential user experiences and needs, especially regarding prior experience developing LLM related applications.

Tasks We designed five distinct tasks of increasing complexity to probe diferent facets of POML’s capabilities.

• Task 1 (T1) involved rewriting an existing plain text prompt into POML and subsequently restyling its output presentation to YAML format using POML’s styling features.

• Task 2 (T2) focused on utilizing POML’s document handling features (<document>) to process TODO items embedded within a Microsoft Word document, showcasing its ability to integrate and present document content efectively.

• Task 3 (T3) required participants to analyze stock market data (alongside its visualization) provided in an Excel spread sheet (<table>) and prompt an LLM for investing recommendations, testing table integration and image presentation.

• Task 4 (T4) explored meta-prompting concepts by asking participants to use an LLM (initially GPT-4o) to generate POML code based on a list of POML examples; they were then asked to adapt the prompt to target a smaller codecompletion model, CodeGemma-2B [82], evaluating POML’s role in managing prompts for diferent models and the perceived dificulty of this adaptation.

• Task 5 (T5), the most complex task, involved translating content from two subtitle files (in TSV format, one from a 22- minute animation, the other from a 45-minute news report)

while preserving specific formatting conventions and timestamps, testing POML’s ability to read, process, and present tabular data subsets in specific formats under constraints.

The code and data associated with these tasks are available in the supplementary material.

Procedure Each participant engaged in a single session lasting approximately 90 minutes. To manage session time efectively, participants were assigned a randomly selected subset of the five tasks. Participants used their own laptops, requiring only VSCode, without additional runtime environment requirements. Sessions began with participants watching a 7-minute introductory video tutorial explaining POML’s core concepts and usage. Subsequently, they were provided with two quickstart code examples and a concise Markdown manual detailing POML syntax and features. They were provided with a VSCode workspace containing the task descriptions, data, and preconfigured access to the GPT-4o and CodeGemma-2B LLMs. Participants were instructed to use a think-aloud protocol, verbalizing their thought processes, challenges, and insights while completing the assigned tasks within the provided VSCode environment equipped with the POML language extension. Following the task completion phase, participants engaged in a semi-structured verbal interview guided by a predefined list of 11 key questions. These questions explored their task experience (completion, time, dificulties), prior prompt usage, perceived usefulness of POML (scenarios, valuable/dificult features, learnability), potential workflow integration, feedback on the VSCode tooling, suggestions for improvement, and any encountered bugs (the full list is provided in Appendix F).

All user study sessions were screen and audio recorded for subsequent detailed analysis. Comprehensive telemetry data was automatically logged, including the time spent on each task, interactions with Language Server Protocol (LSP) features (such as hover help activations, code completion triggers and acceptances), and the complete version history of the POML code written by each participant. Facilitators maintained a minimal intervention policy, ofering assistance only when a participant encountered a significant impediment preventing further progress. The evaluation involved a mixed-methods approach, combining qualitative analysis of the verbal feedback and facilitator observations with quantitative analysis of task completion metrics and telemetry data.

## 8.1 Task Completion and Component Usages

Participants demonstrated high overall task completion rates across the assigned activities. Table 4 details the completion status for each participant across the five tasks. Average task completion times varied considerably based on task complexity and participant diferences, as also shown in Table 4. Simpler tasks, such as T1 (Rewriting/Restyling) and T2 (Document TODOs), were typically completed within approximately 10–15 minutes by assigned participants, suggesting efective basic usability.

Tasks evaluating fundamental POML capabilities were generally completed successfully. Participants generally completed T1 and T2 relatively quickly. T2 specifically demonstrated the perceived value of POML’s document handling features, although one participant (P7) noted occasional performance lag with larger documents. T3 (Stock Analysis) was also successfully completed by most assigned participants, efectively demonstrating POML’s integration and pre sentation capabilities for tabular data. Some participants, however, encountered minor dificulties with the specific syntax for selecting table data subsets in T3. T4 (Meta-Prompting) presented greater challenges. While most participants successfully generated initial POML code using GPT-4o, adapting the prompt for the smaller CodeGemma-2B model proved dificult within the session’s time constraints, reflecting inherent challenges in model-specific prompt adaptation. T5 (Subtitle Translation) represented the most complex task, exhibiting the lowest completion rate and the longest average completion times among assigned participants, as detailed in Table 4. Common dificulties included managing precise TSV for matting, handling potential token limits with the longer input file, and preventing undesired line merging or timestamp inaccuracies. This task efectively probed the limits of managing complex format preservation under constraints using POML.

Table 4: User study results showing task completion and tool interaction metrics. Left Columns: Participant backgrounds. Middle Columns: Task completion status ( = completed, \$= partially completed, –= not assigned) and approximate completion times. Right Columns: Interaction metrics (hover help usage, code completion attempts, items per suggestion, suggestion acceptance rate). Task complexity increased from T1 (prompt rewriting) to T5 (subtitle translation), with T5 requiring more time. Participants showed varied engagement with IDE assistance features.

<table><tr><td rowspan="2">Participant</td><td colspan="2">Prompt Experience</td><td colspan="5">Task Completion</td><td colspan="4">LSP Metrics</td></tr><tr><td>Rate</td><td>LLM-App-related</td><td>T1</td><td>T2</td><td>T3</td><td>T4</td><td>T5</td><td>Hover</td><td>Completion</td><td>Items/Comp</td><td>Accept (%)</td></tr><tr><td>P1</td><td>Novice</td><td>No</td><td>-</td><td>✓ 10min</td><td>✓ 10min</td><td>-</td><td>✓ 1h</td><td>109</td><td>908</td><td>2.38</td><td>21.21</td></tr><tr><td>P2</td><td>Advanced</td><td>Yes</td><td>✓ 20min</td><td>-</td><td>✓ 15min</td><td>◇ 20min</td><td>-</td><td>68</td><td>286</td><td>2.18</td><td>49.37</td></tr><tr><td>P3</td><td>Intermediate</td><td>No</td><td>-</td><td>✓ 10min</td><td>-</td><td>-</td><td>✓ 1h</td><td>35</td><td>402</td><td>3.00</td><td>57.14</td></tr><tr><td>P4</td><td>Intermediate</td><td>No</td><td>-</td><td>✓ 10min</td><td>✓ 10min</td><td>◇ 10min</td><td>-</td><td>24</td><td>226</td><td>2.50</td><td>50.00</td></tr><tr><td>P5</td><td>Novice</td><td>No</td><td>✓ 10min</td><td>✓ 5min</td><td>-</td><td>-</td><td>◇ 40min</td><td>21</td><td>544</td><td>2.55</td><td>27.27</td></tr><tr><td>P6</td><td>Advanced</td><td>Yes</td><td>-</td><td>✓ 10min</td><td>✓ 15min</td><td>✓ 20min</td><td>-</td><td>120</td><td>1282</td><td>2.11</td><td>23.66</td></tr><tr><td>P7</td><td>Intermediate</td><td>Yes</td><td>-</td><td>✓ 10min</td><td>✓ 15min</td><td>✓ 15min</td><td>◇ 20min</td><td>22</td><td>1734</td><td>2.16</td><td>50.82</td></tr><tr><td>Average</td><td>-</td><td>-</td><td>15min</td><td>9min</td><td>13min</td><td>16min</td><td>45min</td><td>57.0</td><td>768.9</td><td>2.41</td><td>39.92</td></tr></table>

![](images/5e551f41c28cf3c78f06905b251062e094346459b8e54f22c3441f958fe23865.jpg)  
Figure 11: Frequency of POML component usage across user study sessions. The chart shows the total count of each com ponent type used by participants. List items (<item>) were most frequently used, followed by captioned paragraphs (<cp>), and the root <poml> tag. Data components (<document>, <table>) and intention components (<task>, <role>) were also commonly used, showing engagement with POML’s data and intention components.

Analysis of component usage frequency, illustrated in Figure 11, reveals participants’ engagement with POML’s core structuring elements. Basic structural components like list items (<item>) and captioned paragraphs (<cp>) were the most frequently employed after the root <poml> tag. Intention components (e.g., <task>, <input>, <role>, <example>) and data integration components (<document>, <table>) also saw significant usage. This pattern indicates that participants actively used POML’s features for structured prompting and data handling throughout the study tasks.

Interaction metrics, presented in the rightmost columns of Table 4, indicate diverse patterns of reliance on the provided IDE tooling assistance. We observe that hover help usage varied widely among individuals, while code completion features were frequently triggered by most participants. However, the acceptance rates for completion suggestions (ranging from 21% to 57%) suggest mixed perceived utility or accuracy of the LSP-provided suggestions. Observations during the sessions confirmed difering programming habits: some participants (P3, P4, P7) used auto-completion extensively, while others (P6) frequently used the hover feature to explore documentation, and some relied more on manual typing or consulting the provided documentation.

## 8.2 User Experience and Qualitative Feedback

Participants’ experiences with POML were largely positive, shaped by their technical backgrounds and task complexity. Feedback consistently highlighted POML’s utility in structuring prompts and integrating data, while also pinpointing areas for potential refinement (§ 9).

Feedback on Core Language Features POML’s capability for integrating diverse data types emerged as a frequently praised strength. Participants consistently valued the built-in components for handling various file types (<document>, <table>, etc.), emphasizing the reduction in manual data preparation efort compared to traditional methods. For example, P7 noted the convenience of reading “various diferent files... PDFs, Word documents, and Excel files,” while P3 found features like “selected records” and “selected columns ... quite helpful.” P4 appreciated how POML simplified previously “troublesome” tasks like “reading documents... reading images,” enabling quick data loading via simple commands. This positive reception aligns with the observed usage of data compo nents in tasks T2, T3, and T5, as shown in Figure 11.

The styling system was also well-received. Participants recognized the value of format control (P1 found the format changing feature “quite cool,” a sentiment echoed by P7 regarding the value of format control). They also praised its suitability for structured tasks like format conversion. P5 described POML as “suitable for struc tured work... especially for file format conversion.”. While tasks within the study can often be resolved with inline attributes only (e.g., in T1, T3, T5), P2 successfully used an external <stylesheet> in T1, demonstrating the feasibility of the approach. However, deeper engagement with complex stylesheets was limited by the study’s scope, leaving the full potential for systematic format man agement largely recognized conceptually.

Development Experience The integrated development toolkit received predominantly positive feedback for enhancing the prompt authoring workflow. The live preview feature was universally praised for providing immediate visual feedback on the rendered prompt structure, thereby reducing cognitive load and improving clarity (P1, P4). The integrated testing feature, particularly its real-time streaming of LLM outputs, was also valued, with P6 finding the stream ing capability “surprisingly impressive.” Participants frequently adopted an iterative edit-preview-test cycle within the IDE, consistent with common prompt engineering practices [102]. Usage patterns for IDE assistance features varied, as discussed in § 8.1. Hover help was frequently used by some participants. For instance, P6 mentioned “frequently using the hover feature to explore avail able documentation”. Auto-completion saw extensive use by others (e.g., P3, P4, P7), indicating active engagement with these assistance tools despite difering individual habits.

Learning Curve Participants’ prior technical experience, particu larly familiarity with HTML/XML markup, significantly influenced their perceived learning curve. Those with relevant backgrounds (P2 found it “elegant like React”; P7 was “familiar with markup languages”) generally found the syntax intuitive. Conversely, par ticipants without such experience (P1 stated “I don’t know HTML very well ... don’t know attributes need to be quoted”) reported a steeper initial learning curve and relied more heavily on the live preview and provided documentation. P6 initially found the number of components somewhat “overwhelming.” The provided documen tation (video, examples, manual) served as crucial initial learning resources, frequently consulted by participants (especially P1, P3, P6). Despite varying adaptation speeds, all participants appeared to gain comfort with basic POML usage within 10–15 minutes of start ing their first task, aided by the IDE’s live preview and diagnostics.

Workflow Integration Participants described diverse existing strategies for managing prompts, ranging from informal methods like using note-taking applications (P1 stated “I currently manage my prompts through OneNote”) or simple text files (P5), to embed ding prompts directly within application code (P2 mentioned “If I write in Python, I often write prompts messily [in Python string]”). Despite these varied habits, a majority (5 of 7) expressed potential for integrating POML into their workflows, particularly for two types of use cases. First, for managing frequently used or complex personal prompts, participants valued the organization POML provides (P1 explained “if I put them in a [code] repo, I can find them,” contrasting with the disorganization of OneNote). Second, for developing LLM applications, participants with LLM-App development experience saw significant value in treating POML files like source code. This approach facilitates standard version control practices (P2 and P6 explicitly mentioned “Git integration”) and improves collaboration through shared, standardized prompt definitions (P6 reflected that “it might be more conducive to my subsequent prompt management”). Integration with Python, though not reflected in the given tasks, was frequently cited as critical for adoption in application development contexts (P1, P5, P6), as well as programmatic prompt generation and incorporation into existing AI/ML pipelines.

Envisioned Values Beyond the study tasks, participants envisioned several practical applications where POML’s structure and data handling would be beneficial. P1 suggested using POML to manage context for writing tasks by embedding related research papers as documents: “let it read several related works first... then let it follow some instructions to write [my article].” P3 similarly saw potential for academic writing support. P2 highlighted the convenience for table processing, stating that without POML, it “would require writing a lot of code and formatting... but with POML it would be convenient,” envisioning its use for “running benchmarks.”

Unexpected Usage Patterns and Desires Observations revealed potential use cases beyond POML’s primary design focus. Some participants (P1, P3, P6) appeared to use data components (e.g., <document>) partly as a convenient way to preview file contents within the IDE, suggesting secondary value as an integrated data viewer. P3 appreciated how POML could “import a file directly, then help me read it out, help me display it,” Occasional comments also hinted at a desire among some advanced users (P6, P7) for lower-level customization options regarding component rendering. Interest was also expressed in exploring agent-like capabilities by writing multiple distinct prompts within a single .poml file, with P5 suggesting “potential for extending the framework towards more complex task orchestration.”

Usage Overhead The frequent use of intention and structural components (Figure 11) suggests that most participants appreciated the explicit structure POML imposes for managing prompt complexity in such scenarios. However, a trade-of regarding usage overhead was noted by several participants (P1, P4, P6). For simple, one-of prompts, the explicit component structure could introduce typing or cognitive overhead compared to plain text, described by P1 and echoed by P5 as potentially “using a sledgehammer to crack a nut.” While POML’s design attempts to minimize this for simple cases (e.g., the root <poml> tag is optional, as discussed in § 4.1), the need to create a file and the mental burden caused by .poml sufix still represents a higher initial cost than typing directly into a chat interface. This feedback suggests POML’s value proposition is strongest for complex, data-intensive prompts where structure, lifecycle maintainability, and reusability are paramount, while it may be overkill for simple, transient plain text prompts.

## 9 Discussion

The case studies and user study ofered practical insights into POML’s application and adoption. Although POML’s strengths were confirmed, the evaluation also highlighted areas for refine ment based on user feedback and task challenges. These findings inform this discussion on improvements, limitations, and future directions.

## 9.1 Suggestions for Improvement

Usability and Developer Experience Improvements Participants suggested several usability enhancements to improve the learning curve and development workflow. A recurring request was for more comprehensive documentation, including searchable references and practical examples covering advanced styling and templating (P2 asked for “documentation that’s easy to look up”). Clearer, more actionable error messages were desired to expedite debugging, as current messages were sometimes found opaque (P1 and P3 stated “Error messages are hard to understand”). Language or tooling simplifications, such as sensible default attributes (P2) or clearer distinctions between similar components (P6), were also pro posed. Performance optimization, particularly for large document handling (P7) and code assistance responsiveness, remains crucial. Refining auto-completion accuracy (P7) and mitigating conflicts with tools like GitHub Copilot (P2) were noted as important for a smoother experience.

Feature Requests User requests focused on enhancing work flow integration and expanding POML’s functionality. Participants desired options to directly save LLM test outputs to files (P6), bypass ing manual copying. Improved mechanisms for managing multi turn conversations within the POML tool were commonly sought by almost all participants. Greater user control over LLM selection and API key management during testing was also requested (P3, P5). Support for additional document formats like LaTeX, particu larly for academic use cases (P3), was suggested. Some novice users indicated a desire for integrated guidance on prompt best practices or model-specific formatting (P1), reflecting known challenges in prompt engineering interfaces [102].

## 9.2 Limitations

Accessibility The current POML VSCode extension (especially the live preview) presents significant accessibility barriers. It lacks optimization for users relying on assistive technologies like screen readers or requiring high-contrast modes. Key areas needing im provement include keyboard navigability, text equivalents for UI elements, suficient color contrast, and font size scaling support. Ad dressing these gaps based on established guidelines [92] is essential to ensure broader usability.

User Study Our user study findings (§ 8) are subject to method ological limitations. The 90-minute sessions restricted deep explo ration of advanced features. The small participant sample (� = 7), though diverse, consisted mainly of technical users, potentially limiting generalizability. The controlled lab setting might not fully reflect real-world project complexities. Furthermore, most partici pants did not deeply engage with complex stylesheets during the tasks. To help mitigate these limitations, we are actively working to open-source POML on GitHub and release the extension on the VSCode Extension Marketplace, which will allow us to gather feedback from a broader and more diverse audience using POML in real-world contexts.

## 9.3 Future Work

Based on user feedback, case study insights, and identified limitations, future work will prioritize enhancing POML’s usability, features, and ecosystem. We will keep improving the developer experience through better accessibility support, augmented docu mentation, refined error diagnostics, performance optimizations, and enhanced SDK usability. Key feature developments include more sophisticated multi-turn conversation management, flexible output handling (e.g., direct file saving), and an expanded template library, potentially incorporating model-specific styling insights (§ 7.2). The structured nature of POML also makes it suitable for exploring automated prompt engineering techniques [44, 48, 105], which is another promising direction for future research.

Beyond core enhancements, we aim to promote POML adoption and demonstrate its value across various domains. We envision POML as a general-purpose prompt markup language. Potential applications include serving as a meta-prompt language in agent systems [50], a structured approach to configure applications like Cursor [2], or a facilitator for industry-level LLM response evaluation workflows as seen in tools like the Azure AI SDK [1]. Further investigation into its utility in complex RAG pipelines, educational tools, domain-specific component libraries, and collaborative prompt engineering environments is also warranted.

## 10 Conclusion

This paper presented POML, a novel Prompt Markup Language designed to address critical challenges in contemporary prompt engineering. POML introduces a component-based structure for enhanced clarity and maintainability, specialized components for efective integration of diverse data types, and a decoupled styling system to systematically manage LLM format sensitivity. Complementing the language, an integrated development toolkit, featuring IDE support and multi-language SDKs, aims to streamline prompt authoring, testing, and management. The efectiveness and practical utility of POML were empirically validated through two distinct case studies alongside a formal user study assessing usability and developer experience. Collectively, these contributions establish POML as a structured, maintainable, and versatile paradigm that addresses prevalent prompt engineering dificulties, thereby enhancing developer workflows, prompt reusability, and collaborative eforts in building sophisticated LLM applications.

## References

[1] Azure AI. 2024. Evaluate your Generative AI application locally with the Azure AI Evaluation SDK. https://learn.microsoft.com/en-us/azure/ai-foundry/howto/develop/evaluate-sdk.

[2] Cursor AI. 2025. Generate Cursor Project Rule (.mdc). https://cursor.directory/ generate.

[3] LangChain AI. 2022. LangChain. https://www.langchain.com/.

[4] LangChain AI. 2023. LangSmith. https://www.langchain.com/langsmith

[5] Angular. 2010. Introduction to components and templates. https://v17.angular. io/guide/architecture-components.

[6] Anthropic. 2024. The Claude 3 Model Family: Opus, Sonnet, Haiku. https:// assets.anthropic.com/m/61e7d27f8c8f5919/original/Claude-3-Model-Card.pdf.

[7] Anthropic. 2024. Use XML tags to structure your prompts. https://docs.anthropic. com/en/docs/build-with-claude/prompt-engineering/use-xml-tags.

[8] anysphere. 2024. priompt. https://github.com/anysphere/priompt.

[9] Ian Arawjo, Chelse Swoopes, Priyan Vaithilingam, Martin Wattenberg, and Elena L Glassman. 2024. ChainForge: A Visual Toolkit for Prompt Engineering and LLM Hypothesis Testing. In Proceedings of the CHI Conference on Human Factors in Computing Systems. 1–18.

[10] AutosseyAI. 2024. prxmpt. https://github.com/AutosseyAI/prxmpt.

[11] Stephen H Bach, Victor Sanh, Zheng-Xin Yong, Albert Webson, Colin Rafel, Nihal V Nayak, Abheesht Sharma, Taewoon Kim, M Saiful Bari, Thibault Fevry, et al. 2022. Promptsource: An integrated development environment and reposi tory for natural language prompts. arXiv preprint arXiv:2202.01279 (2022).

[12] Tim Berners-Lee. 1991. Re: status. Re: X11 BROWSER for WWW. https://lists. w3.org/Archives/Public/www-talk/1991SepOct/0003.html.

[13] Bradybry. 2023. ChatXML: A proposal for a structured LLM prompt method. https://github.com/Bradybry/chatXML.

[14] Tom B Brown. 2020. Language models are few-shot learners. arXiv preprint arXiv:2005.14165 (2020).

[15] Fernando Miguel Carvalho, Luis Duarte, and Julien Gouesse. 2020. Text web templates considered harmful. In Web Information Systems and Technologies: 15th International Conference, WEBIST 2019, Vienna, Austria, September 18–20, 2019, Revised Selected Papers 15. Springer, 69–95.

[16] ChatPDF. 2024. ChatPDF. https://www.chatpdf.com/.

[17] Mark Chen, Jerry Tworek, Heewoo Jun, Qiming Yuan, Henrique Ponde De Oliveira Pinto, Jared Kaplan, Harri Edwards, Yuri Burda, Nicholas Joseph, Greg Brockman, et al. 2021. Evaluating large language models trained on code. arXiv preprint arXiv:2107.03374 (2021)

[18] Nan Chen, Yuge Zhang, Jiahang Xu, Kan Ren, and Yuqing Yang. 2024. VisEval: A Benchmark for Data Visualization in the Era of Large Language Models. IEEE Transactions on Visualization and Computer Graphics (2024).

[19] Karl Cobbe, Vineet Kosaraju, Mohammad Bavarian, Mark Chen, Heewoo Jun, Lukasz Kaiser, Matthias Plappert, Jerry Tworek, Jacob Hilton, Reiichiro Nakano, et al. 2021. Training verifiers to solve math word problems. arXiv preprint arXiv:2110.14168 (2021).

[20] Hai Dang, Lukas Mecke, Florian Lehmann, Sven Goller, and Daniel Buschek. 2022. How to prompt? Opportunities and challenges of zero-and few-shot learning for human-AI interaction in creative applications of generative models. arXiv preprint arXiv:2209.01390 (2022).

[21] Google Deepmind. 2024. Introducing Gemini 2.0: our new AI model for the agentic era. https://blog.google/technology/google-deepmind/google-geminiai-update-december-2024/.

[22] DeepSeek-AI. 2024. DeepSeek-V3 Technical Report. arXiv:2412.19437 [cs.CL] [23] Ant Design. 2015. Ant Design. https://ant.design/.

[24] Michael Desmond and Michelle Brachman. 2024. Exploring Prompt Engineering Practices in the Enterprise. arXiv preprint arXiv:2403.08950 (2024).

[25] Shehzaad Dhuliawala, Mojtaba Komeili, Jing Xu, Roberta Raileanu, Xian Li, Asli Celikyilmaz, and Jason E Weston. [n. d.]. Chain-of-Verification Reduces Hallucination in Large Language Models. In ICLR 2024 Workshop on Reliable and Responsible Foundation Models.

[26] MDN Web Docs. 2025. CSS: Cascading Style Sheets. https://developer.mozilla. org/en-US/docs/Web/CSS.

[27] MDN Web Docs. 2025. HTML: HyperText Markup Language. https://developer. mozilla.org/en-US/docs/Web/HTML.

[28] MDN Web Docs. 2025. JavaScript. https://developer.mozilla.org/en-US/docs Web/JavaScript.

[29] Django documentation. 2024. Templates. https://docs.djangoproject.com/en/5. 1/topics/templates/.

[30] edspencer. 2024. mdx-prompt. https://github.com/edspencer/mdx-prompt.

[31] Bahare Fatemi, Jonathan Halcrow, and Bryan Perozzi. 2024. Talk like a Graph: Encoding Graphs for Large Language Models. In The Twelfth International Conference on Learning Representations.

[32] fixie ai. 2024. AI.JSX — The AI Application Framework for Javascript. https: //github.com/fixie-ai/ai-jsx/.

[33] gensx inc. 2024. gensx. https://github.com/gensx-inc/gensx.

[34] Handlebars. 2011. Handlebars. https://handlebarsjs.com/.

[35] Jia He, Mukund Rungta, David Koleczek, Arshdeep Sekhon, Franklin X Wang, and Sadid Hasan. 2024. Does Prompt Formatting Have Any Impact on LLM Performance? arXiv preprint arXiv:2411.10541 (2024).

[36] Xinyi He, Yihao Liu, Mengyu Zhou, Yeye He, Haoyu Dong, Shi Han, Zejian Yuan, and Dongmei Zhang. 2025. TableLoRA: Low-rank Adaptation on Table Structure Understanding for Large Language Models. arXiv:2503.04396 [cs.CL] https://arxiv.org/abs/2503.04396

[37] Dan Hendrycks, Collin Burns, Steven Basart, Andy Zou, Mantas Mazeika, Dawn Song, and Jacob Steinhardt. 2021. Measuring Massive Multitask Language Understanding. In International Conference on Learning Representations.

[38] Albert Q. Jiang, Alexandre Sablayrolles, Antoine Roux, Arthur Mensch, Blanche Savary, Chris Bamford, Devendra Singh Chaplot, Diego de las Casas,

Emma Bou Hanna, Florian Bressand, Gianna Lengyel, Guillaume Bour, Guillaume Lample, Lélio Renard Lavaud, Lucile Saulnier, Marie-Anne Lachaux, Pierre Stock, Sandeep Subramanian, Sophia Yang, Szymon Antoniak, Teven Le Scao, Théophile Gervet, Thibaut Lavril, Thomas Wang, Timothée Lacroix, and William El Sayed. 2024. Mixtral of Experts. arXiv:2401.04088 [cs.LG] https://arxiv.org/abs/2401.0408

[39] Carlos E Jimenez, John Yang, Alexander Wettig, Shunyu Yao, Kexin Pei, Ofir Press, and Karthik R Narasimhan. 2024. SWE-bench: Can Language Models Resolve Real-world Github Issues?. In The Twelfth International Conference on Learning Representations. https://openreview.net/forum?id=VTF8yNQM66

[40] Jinja. 2022. Jinja – Jinja documentation. https://jinja.palletsprojects.com/en/3.1. x/.

[41] latitude dev. 2024. latitude-llm. https://github.com/latitude-dev/latitude-llm.

[42] Avraham Lef and James T Rayfield. 2001. Web-application development using the model/view/controller design pattern. In Proceedings fifth ieee international enterprise distributed object computing conference. IEEE, 118–127.

[43] leforestier. 2016. yattag. https://github.com/leforestier/yattag.

[44] Zekun Li, Baolin Peng, Pengcheng He, Michel Galley, Jianfeng Gao, and Xifeng Yan. 2024. Guiding large language models via directional stimulus prompting. Advances in Neural Information Processing Systems 36 (2024).

[45] Demiao Lin. 2024. Revolutionizing Retrieval-Augmented Generation with Enhanced PDF Structure Recognition. arXiv:2401.12599 [cs.AI] https://arxiv.org/ abs/2401.12599

[46] Haotian Liu, Chunyuan Li, Qingyang Wu, and Yong Jae Lee. 2023. Visual Instruction Tuning. arXiv:2304.08485 [cs.CV] https://arxiv.org/abs/2304.08485

[47] Xiao Liu, Hao Yu, Hanchen Zhang, Yifan Xu, Xuanyu Lei, Hanyu Lai, Yu Gu, Hangliang Ding, Kaiwen Men, Kejuan Yang, Shudan Zhang, Xiang Deng, Aohan Zeng, Zhengxiao Du, Chenhui Zhang, Sheng Shen, Tianjun Zhang, Yu Su, Huan Sun, Minlie Huang, Yuxiao Dong, and Jie Tang. 2023. AgentBench: Evaluating LLMs as Agents. arXiv preprint arXiv: 2308.03688 (2023).

[48] Yuanye Liu, Jiahang Xu, Li Lyna Zhang, Qi Chen, Xuan Feng, Yang Chen, Zhongxin Guo, Yuqing Yang, and Peng Cheng. 2025. Beyond Prompt Content: Enhancing LLM Performance via Content-Format Integrated Prompt Optimization. arXiv:2502.04295 [cs.CL] https://arxiv.org/abs/2502.04295

[49] Arvid Lunnemark. 2023. Prompt Design. https://arvid.xyz/posts/promptdesign/.

[50] mannaandpoem. 2025. Building OpenManus as a Service. https://openmanus. org/.

[51] mattnigh. 2023. ChatGPT3-Free-Prompt-List: A free guide for learning to create ChatGPT3 Prompts. https://github.com/mattnigh/ChatGPT3-Free-Prompt-List.

[52] Microsoft. 2016. Language Server Protocol. https://microsoft.github.io/languageserver-protocol/.

[53] Microsoft. 2023. Guidance. https://github.com/guidance-ai/guidance.

[54] Microsoft. 2023. Semantic Kernel. https://github.com/microsoft/semantickernel.

[55] Microsoft. 2024. Phi-3 Technical Report: A Highly Capable Language Model Locally on Your Phone. arXiv:2404.14219 [cs.CL] https://arxiv.org/abs/2404. 14219

[56] Yasuhiko Minamide. 2005. Static approximation of dynamically generated web pages. In Proceedings ofthe 14th international conference on World Wide Web. 432–441.

[57] Aditi Mishra, Utkarsh Soni, Anjana Arunkumar, Jinbin Huang, Bum Chul Kwon, and Chris Bryan. 2023. Promptaid: Prompt exploration, perturbation, testing and iteration using visual analytics for large language models. arXiv preprint arXiv:2304.01964 (2023).

[58] MUI. 2014. Material UI. https://mui.com/.

[59] OpenAI. 2020. Playground. https://platform.openai.com/playground.

[60] OpenAI. 2023. ChatGPT. https://chatgpt.com/.

[61] OpenAI. 2024. GPT-3.5 Turbo. https://platform.openai.com/docs/models/gpt-3.5-turbo.

[62] OpenAI. 2024. GPT-4 Technical Report. arXiv:2303.08774 [cs.CL] https://arxiv. org/abs/2303.08774

[63] OpenAI. 2024. GPT-4o System Card. https://cdn.openai.com/gpt-4o-systemcard.pdf.

[64] Panupong Pasupat and Percy Liang. 2015. Compositional Semantic Parsing on Semi-Structured Tables. In Proceedings ofthe 53rd Annual Meeting ofthe Association for Computational Linguistics and the 7th International Joint Conference on Natural Language Processing (Volume 1: Long Papers). 1470–1480.

[65] pezzolabs. 2024. pezzo. https://github.com/pezzolabs/pezzo

[66] {Structured} Prompt. 2023. {Structured} Prompt. https://structuredprompt.com/. [67] promptfoo. 2023. promptfoo. https://www.promptfoo.dev/.

[68] PromptML. 2023. PromptML (Prompt Markup Language). https://www. promptml.org/.

[69] React. 2013. Introducing JSX. https://legacy.reactjs.org/docs/introducing-jsx. html.

[70] React. 2013. React. https://react.dev/.

[71] React. 2024. Server Components. https://react.dev/reference/rsc/servercomponents.

[72] Pranab Sahoo, Ayush Kumar Singh, Sriparna Saha, Vinija Jain, Samrat Mondal, and Aman Chadha. 2024. A systematic survey of prompt engineering in large language models: Techniques and applications. arXiv preprint arXiv:2402.07927 (2024).

[73] Abel Salinas and Fred Morstatter. 2024. The butterfly efect of altering prompts: How small changes and jailbreaks afect large language model performance. arXiv preprint arXiv:2401.03729 (2024).

[74] Tobias Schnabel and Jennifer Neville. 2024. Prompts As Programs: A Structure Aware Approach to Eficient Compile-Time Prompt Optimization. arXiv preprint arXiv:2404.02319 (2024).

[75] Tobias Schnabel and Jennifer Neville. 2024. Symbolic Prompt Program Search: A Structure-Aware Approach to Eficient Compile-Time Prompt Optimization. arXiv:2404.02319 [cs.CL] https://arxiv.org/abs/2404.02319

[76] Melanie Sclar, Yejin Choi, Yulia Tsvetkov, and Alane Suhr. 2024. Quantifying Language Models’ Sensitivity to Spurious Features in Prompt Design or: How I learned to start worrying about prompt formatting. In The Twelfth International Conference on Learning Representations.

[77] Azure AI Services. 2024. Chat Markup Language ChatML (Preview). https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/chatmarkup-language.

[78] Mohit Shridhar, Xingdi Yuan, Marc-Alexandre Côté, Yonatan Bisk, Adam Trischler, and Matthew Hausknecht. 2021. ALFWorld: Aligning Text and Em bodied Environments for Interactive Learning. In Proceedings ofthe International Conference on Learning Representations (ICLR). https://arxiv.org/abs/2010.03768

[79] Hendrik Strobelt, Albert Webson, Victor Sanh, Benjamin Hoover, Johanna Beyer, Hanspeter Pfister, and Alexander M Rush. 2022. Interactive and visual prompt engineering for ad-hoc task adaptation with large language models. IEEE transactions on visualization and computer graphics 29, 1 (2022), 1146–1156.

[80] Yuan Sui, Mengyu Zhou, Mingjie Zhou, Shi Han, and Dongmei Zhang. 2024. Table Meets LLM: Can Large Language Models Understand Structured Table Data? A Benchmark and Empirical Study. arXiv:2305.13062 [cs.CL] https: //arxiv.org/abs/2305.13062

[81] Michiaki Tatsubori and Toyotaro Suzumura. 2009. HTML templates that fly: a template engine approach to automated ofloading from server to client. In Proceedings ofthe 18th international conference on World wide web. 951–960.

[82] CodeGemma Team. 2024. CodeGemma: Open Code Models Based on Gemma. arXiv:2406.11409 [cs.CL] https://arxiv.org/abs/2406.11409

[83] Gemini Team. 2024. Gemini 1.5: Unlocking multimodal understanding across millions of tokens of context. arXiv:2403.05530 [cs.CL] https://arxiv.org/abs/ 2403.05530

[84] Llama Team. 2024. The Llama 3 Herd of Models. arXiv:2407.21783 [cs.AI] https://arxiv.org/abs/2407.21783

[85] Twig. 2009. Twig - The flexible, fast, and secure template engine for PHP. https://twig.symfony.com/.

[86] uithub. 2024. uithub. https://uithub.com.

[87] Juho Vepsäläinen, Arto Hellas, and Petri Vuorimaa. 2023. The State of Disap pearing Frameworks in 2023. In Proceedings ofthe 19th International Conference on Web Information Systems and Technologies, WEBIST 2023 (International Conference on Web Information Systems and Technologies, WEBIST - Proceedings), Francisco Garcia Penalvo and Massimo Marchiori (Eds.). SciTePress, Portugal, 232–241. doi:10.5220/0012174000003584 Publisher Copyright: Copyright © 2023 by SCITEPRESS - Science and Technology Publications, Lda. Under CC license (CC BY-NC-ND 4.0); International Conference on Web Information Systems and Technologies, WEBIST ; Conference date: 15-11-2023 Through 17-11-2023.

[88] Juho Vepsäläinen, Arto Hellas, and Petri Vuorimaa. 2023. The Rise of Disappearing Frameworks in Web Development. Springer Nature Switzerland, 319–326. doi:10.1007/978-3-031-34444-2\_23

[89] Anton Voronov, Lena Wolf, and Max Ryabinin. 2024. Mind your format: Towards consistent evaluation of in-context learning improvements. arXiv preprint arXiv:2401.06766 (2024).

[90] VSCode. 2024. Prompt-tsx. https://github.com/microsoft/vscode-prompt-tsx.

[91] Vue.js. 2014. Components Basics. https://vuejs.org/guide/essentials/component basics.html.

[92] W3C. 2025. Accessibility Fundamentals Overview. https://www.w3.org/WAI fundamentals/.

[93] W3C. 2025. Accessibility Principles. https://www.w3.org/WAI/fundamentals/ accessibility-principles/.

[94] W3C. 2025. W3C. https://www.w3.org/.

[95] Ming Wang, Yuanzhong Liu, Xiaoming Zhang, Songlian Li, Yijie Huang, Chi Zhang, Daling Wang, Shi Feng, and Jigang Li. 2024. LangGPT: Rethinking Structured Reusable Prompt Design Framework for LLMs from the Programming Language. arXiv preprint arXiv:2402.16929 (2024).

[96] Xuezhi Wang, Jason Wei, Dale Schuurmans, Quoc V Le, Ed H Chi, Sharan Narang, Aakanksha Chowdhery, and Denny Zhou. 2023. Self-Consistency Improves Chain of Thought Reasoning in Language Models. In The Eleventh International Conference on Learning Representations.

[97] Jason Wei, Xuezhi Wang, Dale Schuurmans, Maarten Bosma, Fei Xia, Ed Chi, Quoc V Le, Denny Zhou, et al. 2022. Chain-of-thought prompting elicits reasoning in large language models. Advances in neural information processing systems 35 (2022), 24824–24837.

[98] Tongshuang Wu, Ellen Jiang, Aaron Donsbach, Jef Gray, Alejandra Molina, Michael Terry, and Carrie J Cai. 2022. Promptchainer: Chaining large language model prompts through visual programming. In CHI Conference on Human Factors in Computing Systems Extended Abstracts. 1–10.

[99] Chunqiu Steven Xia, Yinlin Deng, Soren Dunn, and Lingming Zhang. 2024. Agentless: Demystifying llm-based software engineering agents. arXiv preprint arXiv:2407.01489 (2024).

[100] Shunyu Yao, Howard Chen, John Yang, and Karthik Narasimhan. 2022. Webshop: Towards scalable real-world web interaction with grounded language agents. Advances in Neural Information Processing Systems 35 (2022), 20744–20757.

[101] Shunyu Yao, Jefrey Zhao, Dian Yu, Nan Du, Izhak Shafran, Karthik R Narasimhan, and Yuan Cao. 2023. ReAct: Synergizing Reasoning and Act ing in Language Models. In The Eleventh International Conference on Learning Representations.

[102] JD Zamfirescu-Pereira, Richmond Y Wong, Bjoern Hartmann, and Qian Yang. 2023. Why Johnny can’t prompt: how non-AI experts try (and fail) to design LLM prompts. In Proceedings of the 2023 CHI Conference on Human Factors in Computing Systems. 1–21.

[103] Yuge Zhang, Qiyang Jiang, Xingyu Han, Nan Chen, Yuqing Yang, and Kan Ren. 2024. Benchmarking Data Science Agents. In Proceedings of the 62nd Annual Meeting ofthe Association for Computational Linguistics (Volume 1: Long Papers), Lun-Wei Ku, Andre Martins, and Vivek Srikumar (Eds.). Association for Computational Linguistics, Bangkok, Thailand, 5677–5700. doi:10.18653/v1/ 2024.acl-long.308

[104] Jefrey Zheng. 2023. Role-Task-Format (RTF) framework for prompting. https: //x.com/thejefreyzheng/status/1660223969755111427.

[105] Yongchao Zhou, Andrei Ioan Muresanu, Ziwen Han, Keiran Paster, Silviu Pitis, Harris Chan, and Jimmy Ba. [n. d.]. Large Language Models are Human-Level Prompt Engineers. In The Eleventh International Conference on Learning Representations.

[106] Jingming Zhuo, Songyang Zhang, Xinyu Fang, Haodong Duan, Dahua Lin, and Kai Chen. 2024. ProSA: Assessing and understanding the prompt sensitivity of LLMs. arXiv preprint arXiv:2410.12405 (2024).

## A POML vs. Other Prompt Markup Languages

There have been various markup languages and frameworks, each addressing specific needs, as summarized in Table 5.

JSX/TSX-based tools like AI.JSX [32] and GenSX [33] primarily target agent and workflow orchestration using high-level compo nents within the Node.js ecosystem. Others, such as VSCode Prompt TSX [90], Priompt [8], Prxmpt [10], and MDXPrompt [30], focus on prompt authoring using JSX/TSX or MDX syntax, often integrating closely with specific runtime environments (e.g., Node.js) or priori tizing features like context length management via priority systems. Specialized formats like ChatML [77] define role-based structures for conversational history, while PromptML [68] proposes a custom DSL focused on intention components but currently lacks integrated tooling. SAMMO [75] takes a distinct approach, using a Python API for programmatic manipulation and structure-aware optimization rather than direct markup authoring.

In contrast to these approaches, POML aims for a comprehensive, standalone solution distinguished by several key characteristics evident in the comparison. It provides a language-agnostic runtime, enhancing portability compared to tools tied to Node.js or Python. POML incorporates versatile components covering basic structure, intention expression, and data integration, ofering arguably the most extensive built-in support among the listed tools for diverse data types like tables, documents, and webpages. POML also inte grates a unique CSS-like styling system for decoupling presentation from content and provides a full VS Code IDE extension, seeking to unify structure, data handling, styling, and development tooling within a single cohesive framework more completely than other approaches listed in Table 5.

## B Templating Engine Design Details

To support the creation of dynamic and data-driven prompts, POML integrates a built-in templating engine. This capability is inspired by widely adopted templating systems in web development frame works [5, 29, 34, 40, 69, 85, 91] and common practices in existing prompting frameworks [3, 53]. Providing an integrated engine en hances POML’s utility, particularly for scenarios where prompts need to be generated dynamically based on runtime data with out external scripting languages (DG2), contributing to eficient development workflows (DG4).

The engine allows for the insertion of variable values directly into the prompt text using a familiar double curly brace syntax: {{variable}}. Its syntax for variables and control structures draws inspiration specifically from popular engines like Jinja and Handle bars [34, 40]. These variables can represent contextual placeholders that are populated at runtime from external data sources (e.g., docu ments, table records) or defined programmatically within the POML document itself using the <let> tag, enabling dynamic data binding and temporary variable assignment within the template logic.

Beyond simple variable substitution, the templating engine supports essential control structures for generating complex prompt logic dynamically. Iteration over data collections (like lists or arrays) is handled using a for attribute, allowing repetitive structures to be generated concisely (e.g., <list><item for="file in files">{{file.description}}</item></list> would create a list item for each object in the files collection). Conditional rendering of prompt sections is achieved through if/else-like constructs, enabling parts of the prompt to be included or excluded based on the evaluation of variable values or logical expressions (e.g., conditionally including a detailed explanation section only if a verbose flag is set to true).

The inclusion of this integrated templating engine ofers several advantages for prompt engineering. It significantly reduces redundancy by allowing developers to define reusable prompt struc tures that can be populated with diferent data inputs, rather than creating many similar static prompts. Compared to constructing prompts through manual string manipulation or concatenation in a general-purpose programming language, which can be often errorprone and less readable [15], POML’s templating approach makes the prompt structure more visually apparent and closer to a “What You See Is What You Get” (WYSIWYG) experience, simplifying the debugging process. The engine’s standalone capability provides dynamic prompting capabilities without mandating the use of an external programming language wrapper, diferentiating POML from some other markup approaches that primarily serve as static data formats [13, 30, 68].

## C Three-Pass Rendering Framework

The POML implementation employs a three-pass rendering framework. This architecture processes the POML markup in three distinct stages: first, a “Parser” pass transforms the input into React JSX components; second, React processes these components to build a comprehensive Intermediate Representation (IR); and third, a “Writer” pass converts this IR into the desired final output format (e.g., Markdown, JSON). The primary motivation for this three-pass approach is the clear separation of concerns. The first pass (Parser) focuses exclusively on parsing the input markup, validating its structure, applying templating, stylesheets, and transforming it into React components. The second pass (React processing) focuses on generating a detailed IR with complete metadata. The third pass (Writer) is solely responsible for traversing the validated IR and serializing it into a specific target format. This separation minimizes interdependencies, ensuring that changes related to styling or data handling do not inadvertently break the final rendering logic.

This three-tier separation fosters flexibility and extensibility. Adding support for new output formats only requires implementing a new Writer module, without modifying the core parsing, templating, or styling logic. Feature additions are simplified as each pass addresses a distinct, well-defined set of tasks. From a performance perspective, the generated IR can be cached and reused to produce multiple output formats (e.g., generating both a plain text version and a chat-structured version simultaneously) without incurring the cost of re-parsing the original POML source, which is particularly beneficial for large prompts involving extensive data components.

The first pass, executed by the Parser module, begins by parsing the raw POML markup. It identifies all known POML tags (e.g., <task>, <document>, <table>) and their attributes. The parser validates the markup structure against the POML specification, flagging malformed tags or invalid attributes, often with a degree of error tolerance to handle minor issues without halting processing entirely (§ 5.1). The template engine (§ 4.4) executes control flow attributes like for-loops and if-else conditions. Variable substitutions using the {{...}} syntax are performed, resolving references to internal variables or data loaded from external sources (e.g., via <let src="...">). Styling rules are applied from both the <stylesheet> tag and inline style attributes, resolving conflicts and computing final style properties for each element. The Parser then transforms these validated elements into React JSX components, preparing them for the second pass.

Table 5: Comparison of POML with other Prompt Markup Languages

<table><tr><td>Markup Language</td><td>Markup Syntax</td><td>Runtime Env.</td><td>Selling Point</td><td>Key Components</td><td>Data Support</td><td>Styling</td><td>Dev Tooling</td></tr><tr><td>AI.JSX [32]</td><td>JSX/TSX</td><td>Node.js</td><td>Agents &amp; Work-flows</td><td>High-level components (Chat completion, Tool use, Q&amp;A)</td><td>Relies on external libraries</td><td>-</td><td>NextJS support, LangChainJS integration</td></tr><tr><td>GenSX [33]</td><td>JSX/TSX</td><td>Node.js</td><td>Agents &amp; Work-flows</td><td>High-level work-flow/agent components</td><td>Text</td><td>-</td><td>TypeScript tool-ing</td></tr><tr><td>VSCode Prompt TSX [90]</td><td>TSX</td><td>Node.js (VS Code Ext)</td><td>Prompt (VS Code)</td><td>Role components (User/Asst), Tool (), File ( ) integra-tion</td><td>Chat history, VS Code API data (files), Tool results</td><td>Priority system (manages length)</td><td>VS Code Ext dev env (TSX/TS sup-port)</td></tr><tr><td>Priompt [8]</td><td>JSX/TSX</td><td>Node.js</td><td>Writing Prompt</td><td>Message &amp; Structural components (, etc.); Priority system (p/prel)</td><td>Image support, JSON data</td><td>Priority system (manages length)</td><td>Preview WebUI</td></tr><tr><td>Prxempt [10]</td><td>JSX</td><td>Node.js</td><td>Writing Prompt</td><td>Utility elements (, etc.), Priority (), Space control, Data serializa-tion (,)</td><td>Primitives (, Dates (), Objects (, etc.); Space control</td><td>Basic text format (, etc.); Space control</td><td>JSX/TS support, Standard Node.js tooling</td></tr><tr><td>MDXPrompt [30]</td><td>MDX (Mark-down + JSX)</td><td>Node.js</td><td>Writing Prompt</td><td>Mix structured/unstructured text, Default com-ponents (, )</td><td>Chat history, JSON data</td><td>-</td><td>MDX/React ecosystem</td></tr><tr><td>ChatML (OpenAI) [77]</td><td>Custom format (Roles)</td><td>Language-Agnostic</td><td>Writing Prompt</td><td>Role-based messages (system, user, assistant, tool)</td><td>Text, Images</td><td>Customizable chat tem-plates</td><td>OpenAI SDKs</td></tr><tr><td>PromptML [68]</td><td>Custom DSL</td><td>Language-Agnostic</td><td>Writing Prompt</td><td>Intention compo-nents (@context, @objective, @instructions, etc.)</td><td>Text</td><td>-</td><td>Python Parser</td></tr><tr><td>SAMMO [75]</td><td>Python API + Mark-down</td><td>Python</td><td>Writing Prompt</td><td>Programmatic manipu-lation, Structure-aware optimization algos</td><td>Relies on Python data libs</td><td>-</td><td>Python dev env, LLM Runner inte-grations</td></tr><tr><td>POML</td><td>HTML-like DSL</td><td>Language-agnostic</td><td>Writing Prompt</td><td>Versatile (basic struc-ture + intention + data)</td><td>Comprehensive (tables, docs, webpages)</td><td>CSS-like styling system</td><td>Full VS Code IDE extension</td></tr></table>

In the second pass, React processes the JSX components gener ated by the Parser. Using React’s virtual DOM concept, this pass constructs a comprehensive Intermediate Representation (IR) - an in-memory tree of structured nodes corresponding to the POML elements, their resolved content, computed styles, and extensive metadata including original source positions and serialization hints. This IR contains 21 distinct node types (Appendix D) and captures all information needed for the final rendering stage, creating a clean, validated representation ready for the third pass.

The third pass is handled by a selected Writer module. Its purpose is to convert the structured Intermediate Representation (IR)

```txt
<poml>
    <role>You are a culinary assistant.</role>
    <task>
    Summarize a recipe.
    Focus on key steps and ingredients.
</task>
    <let name="example" src="example.json" />
    <example syntax="yaml">
    <input>
    <p>Recipe: {{example.recipe}}</p>
    <p>Total Time: {{example.prep_time+example.cook_time}}</p>
    <p>Ingredients Needed: <list>
    <item for="ing in example.ingredients">{{ing}}</item>
    </list></p>
    </input>
    <output><document src="recipe_summary.txt" /></output>
    </example>
    <stylesheet>
    {"role": {"captionStyle": "bold"}, "task": {"captionStyle": "bold"}
    </stylesheet>
</poml>
```

![](images/cca9778968aac5e765008c245582c77c7f93c7aaa0bd2fa0d4791ba87781f925.jpg)  
Figure 12: The POML three-pass rendering architecture: (1)->(2) The Parser transforms POML markup into ReactJSX components, (2)->(3) React processes these components into a detailed Intermediate Representation (IR) that captures content structure, styling, and metadata, and (3)->(4) specialized Writers convert the IR into various output formats such as JSON or Markdown.

generated by React into a final, usable output format, such as Mark down, plain text, or a specific JSON structure required by an LLM API.

The Writer traverses the IR tree, visiting each node (e.g., an IR node representing a <list>, <img>, or <document>). Based on the type of the IR node and the target output format, the Writer seri alizes the node’s content appropriately. For example, a list node might be rendered as a bulleted or numbered list in Markdown, while a table node could be formatted as CSV or a Markdown table depending on the Writer’s configuration and the style attributes cap tured in the IR. Furthermore, the Writer propagates and computes metadata associated with each node, such as the “speaker” attribute. This allows the Writer to structure the output appropriately for diferent contexts, for instance, by splitting the final rendered text into distinct sections based on the speaker (e.g., “human”, “system”) if required by the target format (like chat completion APIs).

Diferent Writer modules can be implemented and selected to produce various outputs from the exact same IR. This architecture makes it straightforward to extend POML to support new target formats (e.g., LaTeX, specific API JSON schemas) by simply creating a new Writer implementation without modifying the earlier passes.

Writers are designed with error tolerance in mind. They can handle partially formed IR nodes (if errors occurred during earlier passes but were tolerated) or missing data references that could not be resolved. If configuration parameters specific to the writer (e.g., a required CSV delimiter) are missing or invalid, the writer typically alerts the developer but attempts to continue converting the parts of the IR that are unafected.

This three-pass structure consistently maintains the separation ofconcerns between prompt logic/content and final presentation/layout. Updates to data sources (src attributes) or styling rules (<stylesheet>) captured during the earlier passes generally do not require any changes to the Writer logic. This reinforces POML’s commitment to a modular and robust approach to prompt engineering, aligning with design goals for Reusability (DG1) and Style Management (DG3).

## D Intermediate Representation (IR) Specifications

## D.1 Attributes Applicable to All Tags

The following attributes can be applied to any tag in the representation:

• speaker (ai/human/system): The speaker of the current con tent

• original-start-index (integer): The start ofset of the ele ment corresponding to the current one in the original docu ment

• original-end-index (integer): The end ofset of the element corresponding to the current one in the original document

## D.2 Tag Definitions

any Represents a generic container for arbitrary data values. Useful for storing dynamic or unstructured content.

• type (string): The data type of the value (‘string’, ‘integer’, ‘float’, ‘boolean’, ‘array’, ‘object’, ‘bufer’, ‘null’, or ‘undefined’).

• name (string): An optional identifier for the data.

b Represents text that should be displayed in boldface. Useful for highlighting important words or phrases.

code Represents a block or inline fragment of code. It can option ally include language and formatting attributes.

• inline (boolean): Indicates whether the code is inline (true) or a block element (false).

• lang (string): Specifies the programming language or syntax highlighting mode.

• blank-line (boolean): Inserts a blank line before and after the code block if inline = false.

env Represents a formatting environment or container to specify how nested content should be output.

• presentation (string): The output style or format mode (‘markup’, ‘serialize’, ‘free’, or ‘multimedia’).

• markup-lang (string): The specific markup language, required only if presentation = ‘markup’.

• serializer (string): The name of the serializer, required only if presentation = ‘serialize’.

• writer-options (object): Optional parameters passed to the writer constructor for customizing output.

## h Represents a heading element.

• level (integer): Indicates the heading level. Typically ranges from 1 (highest level) to 6 (lowest level).

i Represents text that should be displayed in italics. Useful for emphasizing words or phrases.

img Represents an image element.

• base64 (string): The base64-encoded image data.

• alt (string): Alternative text describing the image.

• position (string): The placement of the image relative to text, such as ‘here’, ‘top’, or ‘bottom’.

• type (string): The image MIME type (e.g., ‘image/jpeg’, ‘image/png’).

item Represents a single item within a list. Typically used as a child element of “list”.

list Represents an ordered or unordered list of items.

• list-style (string): The style of the list bullets or enumeration (e.g., ‘star’, ‘dash’, ‘decimal’)

nl Inserts newline characters.

• count (integer): Specifies how many newline characters to insert.

obj Represents a data object, typically stored in JSON format.

• data (object): A valid JSON object containing the structured data.

p Represents a paragraph of text. Useful for dividing content into readable blocks.

• blank-line (boolean): Inserts a blank line before and after the paragraph when true.

s Represents text that should be displayed with a strikethrough style.

span Represents an inline container for text without additional formatting. Useful for applying attributes without changing display structure.

table Represents a table structure containing rows and cells.

tbody Represents the body section of a table, containing the majority of data rows.

tcell Represents a single cell within a table row.

text Represents raw or unformatted text content.

thead Represents the header section ofa table, typically containing column headings.

trow Represents a single row within a table, containing one or more cells.

u Represents text that should be displayed with an underline.

## E Details of TableQA Case Study

A detailed example of the prompt structure used in our TableQA case study is provided below, as discussed in the main text. Figure 13 illustrates the components involved.

Figure 13(a) presents the POML template crafted for this task. It defines the overall structure provided to the language model, encompassing the core task instruction, specific requirements for the output format (including explanation prefixes and separators), few-shot examples demonstrating the desired input-output behavior, and the placeholder for the actual query which includes the table data (columns and records) and the user question.

Figure 13(b) shows an example of the corresponding JSON stylesheet. This stylesheet controls the rendering and formatting aspects of the POML prompt, specifying details such as the syntax for diferent elements (e.g., markdown for POML, csv for tables), styling for instructional text and captions (e.g., bolding, headers, specific question/answer prefixes like “Q”-“A”), and the presentation ofexamples.

![](images/b4e95c389d95d53025593e2fb8ac860db822208ada72569b5ef8aa611cd67370.jpg)

```txt
<poml>
    <task className="instruction">
    Here is the table to answer this question.
    </task>
    <output-format className="instruction">
    Please provide your explanation first, then answer the question in a short phrase starting by 'Therefore, the answer is:', 
    If the answer contains multiple items, use three hashtags (<code>###</code>) to separate them.
    </output-format>
    <examples>
    <example for="example in examples">
    <input>
    <table columns="{{ example.table.columns }}"
    records="{{ example.table.records }}"
    />
    <qa>{{ example.question }}</qa>
    </input>
    <output>
    {{ example.explanation }}
    Therefore, the answer is: {{ example.answer }}
    </output>
    </example>
    </examples>
    <cp className="query" caption="Query" captionSerialized="query">
    <table columns="{{ query.table.columns }}"
    records="{{ query.table.records }}"
    />
    <qa>{{ query.question }}</qa>
    </cp>
</poml>
```

(a) Prompt (POML) for TableQA Case Study  
```json
{
    "poml": {
    "syntax": "markdown"
    },
    "table": {
    "syntax": "csv"
    },
    ".instruction": {
    "captionStyle": "bold",
    "captionTextTransform": "none",
    "captionColon": true
    },
    "examples": {
    "captionStyle": "header",
    "introducer": "Here are some examples:", 
    "chat": false
    },
    "example": {
    "captionStyle": "hidden"
    },
    "qa": {
    "captionStyle": "bold",
    "questionCaption": "Q",
    "answerCaption": "A"
    },
    ".query": {
    "captionStyle": "bold"
    }
}
```  
(b) Stylesheet Example for TableQA Case Study  
Figure 13: Example of POML usage for the TableQA case study (§ 7.2, Appendix E). (a) The POML prompt template defining the task instructions, required output format, few shot examples, and the query structure containing the table and question. (b) The correspondingJSON stylesheet example specifying formatting and presentation rules for elements within the POML prompt, such as overall syntax, caption styles, and introducer text.

This separation of content (POML) and presentation (stylesheet) allows for flexible prompt customization and management.

Analysis of style preferences across models, visualized in the correlation heatmap (Figure 14), revealed distinct model groupings. For instance, Phi-3 Medium, GPT-4o Mini, and Claude 3 Haiku formed a cluster exhibiting similar positive correlations in their style rankings, suggesting shared preferences. Conversely, Mistral

Figure 14: Correlation matrix showing relationships between LLMs based on their performance rankings across 100 prompt styles in the TableQA task (§ 7.2, Appendix E). Cells show Spearman correlation coeficients between model style rankings (Red: positive/similar preferences; Blue: negative/dissimilar preferences). The diagonal shows the selfcorrelation score for each model (see Table 2 for definition and values), indicating style ranking stability. The selfcorrelation score indicates the stability of the style performance ranking. It is computed by randomly splitting the 283 samples into two equal halves, calculating the accuracy of each of the 100 styles on both halves, and finding the Spearman correlation between the two resulting style rankings. This process is repeated 1000 times, and the mean correlation is reported; higher values indicate more stable style rankings across diferent data subsets.

AI 8x7B and LLaMA 3 70B formed another group, often showing negative correlations with the first cluster, indicating fundamentally diferent sensitivities to styling choices. Deeper analysis of individual feature impacts (Table 6) highlighted specific sensitivities with statistical significance. Using plain text for example bodies sig nificantly benefited models like Claude 3 Haiku and Phi-3 Medium but harmed LLaMA 3 70B and Mistral AI 8x7B (� < 0.01). Adopting a chat-like format for examples helped LLaMA 3 70B and Mistral AI 8x7B but was detrimental to several others (� < 0.01). Hiding structural elements like QA captions negatively impacted most models but surprisingly benefited GPT-3.5 Turbo (� < 0.05). Complex interaction efects were also observed, where the combined impact of certain style features difered from the sum of their individual efects, indicating non-linear relationships in how styling elements influence performance.

(10) What improvements or additional features do you suggest for POML or its VSCode integration?

(9) Do you like the VSCode integration of POML (preview, test ing, auto-completion)? Why or why not?

(11) Did you encounter any bugs or errors, and how did these afect your overall experience of POML?

(8) How do you foresee integrating POML into your existing workflow or pipeline?

(7) Do you consider the POML syntax easy to learn and worth while to master?

(6) Which parts or features of POML do you find most dificult to use, and why?

(5) Which parts or features of POML do you find most valuable, and why?

Table 6: Impact analysis of specific prompt styling choices on TableQA accuracy across diferent LLMs (§ 7.2, Appendix E). Each cell indicates whether a feature (row) significantly improved $( \checkmark ) .$ , had no significant efect (–), or significantly harmed (✗) performance for a given LLM (column), based on statistical significance tests (Mann-Whitney U test comparing styles with vs. without the feature; significance levels indicated). The bottom rows show examples of interaction efects for specific feature combinations.

<table><tr><td>Style Preference</td><td>Claude</td><td>DeepSeek</td><td>Gemini</td><td>3.5-Turbo</td><td>4o-Mini</td><td>LLaMA-3</td><td>Mistral</td><td>Phi-3</td></tr><tr><td>Example Body = Text</td><td> $\checkmark p < 0.01$ </td><td> $\checkmark p < 0.05$ </td><td>-</td><td>-</td><td> $\checkmark p < 0.01$ </td><td> $\times p < 0.01$ </td><td> $\times p < 0.01$ </td><td> $\checkmark p < 0.01$ </td></tr><tr><td>Example Body = Introducer</td><td> $\checkmark p < 0.01$ </td><td>-</td><td> $\checkmark p < 0.01$ </td><td> $\times p < 0.01$ </td><td> $\checkmark p < 0.01$ </td><td>-</td><td> $\times p < 0.01$ </td><td> $\checkmark p < 0.01$ </td></tr><tr><td>Overall Syntax = HTML</td><td>-</td><td>-</td><td> $\checkmark p < 0.05$ </td><td> $\times p < 0.01$ </td><td> $\checkmark p < 0.01$ </td><td>-</td><td> $\times p < 0.05$ </td><td> $\checkmark p < 0.01$ </td></tr><tr><td>Overall Syntax = XML</td><td> $\checkmark p < 0.05$ </td><td>-</td><td>-</td><td> $\checkmark p < 0.05$ </td><td>-</td><td> $\times p < 0.05$ </td><td> $\times p < 0.01$ </td><td>-</td></tr><tr><td>Table Syntax = CSV</td><td> $\checkmark p < 0.05$ </td><td> $\times p < 0.01$ </td><td> $\times p < 0.01$ </td><td>-</td><td>-</td><td>-</td><td>-</td><td> $\checkmark p < 0.01$ </td></tr><tr><td>Overall Syntax = Markdown</td><td>-</td><td>-</td><td>-</td><td> $\checkmark p < 0.01$ </td><td> $\times p < 0.01$ </td><td>-</td><td> $\checkmark p < 0.01$ </td><td> $\times p < 0.01$ </td></tr><tr><td>Example Body = Chat</td><td> $\times p < 0.01$ </td><td>-</td><td>-</td><td>-</td><td> $\times p < 0.01$ </td><td> $\checkmark p < 0.01$ </td><td> $\checkmark p < 0.01$ </td><td> $\times p < 0.01$ </td></tr><tr><td>Example Body = Chat w. Introducer</td><td> $\times p < 0.01$ </td><td> $\times p < 0.05$ </td><td> $\times p < 0.05$ </td><td>-</td><td> $\times p < 0.01$ </td><td> $\checkmark p < 0.05$ </td><td> $\checkmark p < 0.01$ </td><td> $\times p < 0.01$ </td></tr><tr><td>QA Caption = Hidden</td><td> $\times p < 0.01$ </td><td>-</td><td> $\times p < 0.01$ </td><td> $\checkmark p < 0.05$ </td><td> $\times p < 0.01$ </td><td>-</td><td>-</td><td> $\times p < 0.01$ </td></tr><tr><td>Overall Syntax = Markdown, Example Body = Introducer</td><td> $\checkmark p < 0.01$ </td><td> $\checkmark p < 0.05$ </td><td> $\checkmark p < 0.05$ </td><td>-</td><td> $\checkmark p < 0.05$ </td><td>-</td><td> $\times p < 0.01$ </td><td> $\checkmark p < 0.01$ </td></tr><tr><td>Instruction Header = Header, Example Body = Introducer</td><td> $\checkmark p < 0.05$ </td><td>-</td><td> $\checkmark p < 0.05$ </td><td> $\times p < 0.01$ </td><td> $\checkmark p < 0.05$ </td><td>-</td><td>-</td><td> $\checkmark p < 0.05$ </td></tr><tr><td>Example Body = Introducer, QA Caption = Bold-Upper</td><td> $\checkmark p < 0.05$ </td><td>-</td><td> $\checkmark p < 0.05$ </td><td>-</td><td> $\checkmark p < 0.05$ </td><td>-</td><td> $\times p < 0.05$ </td><td> $\checkmark p < 0.01$ </td></tr><tr><td>Example Body = Introducer, QA Body = Question-Explanation</td><td> $\checkmark p < 0.01$ </td><td>-</td><td> $\checkmark p < 0.05$ </td><td> $\times p < 0.05$ </td><td> $\checkmark p < 0.01$ </td><td>-</td><td>-</td><td> $\checkmark p < 0.01$ </td></tr><tr><td>Example Body = Text, QA Body = Question-Explanation</td><td> $\checkmark p < 0.01$ </td><td> $\checkmark p < 0.05$ </td><td>-</td><td> $\checkmark p < 0.05$ </td><td> $\checkmark p < 0.01$ </td><td> $\times p < 0.01$ </td><td> $\times p < 0.01$ </td><td> $\checkmark p < 0.05$ </td></tr><tr><td>Overall Syntax = Markdown, Example Body = Text</td><td> $\checkmark p < 0.01$ </td><td> $\checkmark p < 0.05$ </td><td>-</td><td> $\checkmark p < 0.01$ </td><td> $\checkmark p < 0.01$ </td><td> $\times p < 0.01$ </td><td> $\times p < 0.01$ </td><td> $\checkmark p < 0.01$ </td></tr></table>

(4) In your opinion, for which scenarios is POML not useful?

(3) In your opinion, for which scenarios is POML most useful?

(2) Do you have prior experience with using prompts? In what scenarios do you typically employ prompts?

The following questions were used to guide the semi-structured interviews with users. The questions were designed to elicit detailed feedback on the user’s experience with POML, its features, and their suggestions for improvement.

(1) What tasks do you find most challenging and why?

## F Semi-structured Verbal Interview Questions