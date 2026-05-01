[![Hugging Face's logo](https://huggingface.co/front/assets/huggingface_logo-noborder.svg)Hugging Face](https://huggingface.co/)

- [Models](https://huggingface.co/models)
- [Datasets](https://huggingface.co/datasets)
- [Spaces](https://huggingface.co/spaces)
- [Buckets new](https://huggingface.co/storage)
- [Docs](https://huggingface.co/docs)
- [Enterprise](https://huggingface.co/enterprise)
- [Pricing](https://huggingface.co/pricing)

- * * *

- [Log In](https://huggingface.co/login)
- [Sign Up](https://huggingface.co/join)

# [![](https://cdn-avatars.huggingface.co/v1/production/uploads/5dd96eb166059660ed1ee413/WtA3YYitedOr9n02eHfJe.png)](https://huggingface.co/google)  [google](https://huggingface.co/google)  /      [embeddinggemma-300m](https://huggingface.co/google/embeddinggemma-300m)    like1.62k           Follow ![](https://cdn-avatars.huggingface.co/v1/production/uploads/5dd96eb166059660ed1ee413/WtA3YYitedOr9n02eHfJe.png)Google53.6k

[Sentence Similarity](https://huggingface.co/models?pipeline_tag=sentence-similarity) [sentence-transformers](https://huggingface.co/models?library=sentence-transformers) [Safetensors](https://huggingface.co/models?library=safetensors) [gemma3\_text](https://huggingface.co/models?other=gemma3_text) [feature-extraction](https://huggingface.co/models?other=feature-extraction) [text-embeddings-inference](https://huggingface.co/models?other=text-embeddings-inference) [Eval Results](https://huggingface.co/models?other=eval-results)

arxiv:2509.20354

License:gemma

[Model card](https://huggingface.co/google/embeddinggemma-300m) [FilesFiles and versions\\
xet](https://huggingface.co/google/embeddinggemma-300m/tree/main) [Community\\
42](https://huggingface.co/google/embeddinggemma-300m/discussions)

Deploy

Use this model

## Access EmbeddingGemma on Hugging Face

This repository is publicly accessible, but you have to accept the conditions to access its files and content.

To access EmbeddingGemma on Hugging Face, you’re required to review and agree to Google’s usage license. To do this, please ensure you’re logged in to Hugging Face and click below. Requests are processed immediately.

[Log in](https://huggingface.co/login?next=%2Fgoogle%2Fembeddinggemma-300m) or [Sign Up](https://huggingface.co/join?next=%2Fgoogle%2Fembeddinggemma-300m) to review the conditions and access this model content.

- [EmbeddingGemma model card](https://huggingface.co/google/embeddinggemma-300m#embeddinggemma-model-card "EmbeddingGemma model card")
  - [Model Information](https://huggingface.co/google/embeddinggemma-300m#model-information "Model Information")
    - [Description](https://huggingface.co/google/embeddinggemma-300m#description "Description")
    - [Inputs and outputs](https://huggingface.co/google/embeddinggemma-300m#inputs-and-outputs "Inputs and outputs")
    - [Citation](https://huggingface.co/google/embeddinggemma-300m#citation "Citation")
    - [Usage](https://huggingface.co/google/embeddinggemma-300m#usage "Usage")
  - [Model Data](https://huggingface.co/google/embeddinggemma-300m#model-data "Model Data")
    - [Training Dataset](https://huggingface.co/google/embeddinggemma-300m#training-dataset "Training Dataset")
    - [Data Preprocessing](https://huggingface.co/google/embeddinggemma-300m#data-preprocessing "Data Preprocessing")
  - [Model Development](https://huggingface.co/google/embeddinggemma-300m#model-development "Model Development")
    - [Hardware](https://huggingface.co/google/embeddinggemma-300m#hardware "Hardware")
    - [Software](https://huggingface.co/google/embeddinggemma-300m#software "Software")
  - [Evaluation](https://huggingface.co/google/embeddinggemma-300m#evaluation "Evaluation")
    - [Benchmark Results](https://huggingface.co/google/embeddinggemma-300m#benchmark-results "Benchmark Results")
    - [Prompt Instructions](https://huggingface.co/google/embeddinggemma-300m#prompt-instructions "Prompt Instructions")
  - [Usage and Limitations](https://huggingface.co/google/embeddinggemma-300m#usage-and-limitations "Usage and Limitations")
    - [Intended Usage](https://huggingface.co/google/embeddinggemma-300m#intended-usage "Intended Usage")
    - [Limitations](https://huggingface.co/google/embeddinggemma-300m#limitations "Limitations")
    - [Ethical Considerations and Risks](https://huggingface.co/google/embeddinggemma-300m#ethical-considerations-and-risks "Ethical Considerations and Risks")
    - [Benefits](https://huggingface.co/google/embeddinggemma-300m#benefits "Benefits")

# EmbeddingGemma model card

**Model Page**: [EmbeddingGemma](https://ai.google.dev/gemma/docs/embeddinggemma)

**Resources and Technical Documentation**:

- [Responsible Generative AI Toolkit](https://ai.google.dev/responsible)
- [EmbeddingGemma on Kaggle](https://www.kaggle.com/models/google/embeddinggemma/)
- [EmbeddingGemma on Vertex Model Garden](https://console.cloud.google.com/vertex-ai/publishers/google/model-garden/embeddinggemma)

**Terms of Use**: [Terms](https://ai.google.dev/gemma/terms)

**Authors**: Google DeepMind

## Model Information

### Description

EmbeddingGemma is a 300M parameter, state-of-the-art for its size, open embedding model from Google, built from Gemma 3 (with T5Gemma initialization) and the same research and technology used to create Gemini models. EmbeddingGemma produces vector representations of text, making it well-suited for search and retrieval tasks, including classification, clustering, and semantic similarity search. This model was trained with data in 100+ spoken languages.

The small size and on-device focus makes it possible to deploy in environments with limited resources such as mobile phones, laptops, or desktops, democratizing access to state of the art AI models and helping foster innovation for everyone.

For more technical details, refer to our paper: [EmbeddingGemma: Powerful and Lightweight Text Representations](https://arxiv.org/abs/2509.20354).

### Inputs and outputs

- **Input:**

  - Text string, such as a question, a prompt, or a document to be embedded
  - Maximum input context length of 2048 tokens
- **Output:**

  - Numerical vector representations of input text data
  - Output embedding dimension size of 768, with smaller options available (512, 256, or 128) via Matryoshka Representation Learning (MRL). MRL allows users to truncate the output embedding of size 768 to their desired size and then re-normalize for efficient and accurate representation.

### Citation

```none
@article{embedding_gemma_2025,
    title={EmbeddingGemma: Powerful and Lightweight Text Representations},
    author={Schechter Vera, Henrique* and Dua, Sahil* and Zhang, Biao and Salz, Daniel and Mullins, Ryan and Raghuram Panyam, Sindhu and Smoot, Sara and Naim, Iftekhar and Zou, Joe and Chen, Feiyang and Cer, Daniel and Lisak, Alice and Choi, Min and Gonzalez, Lucas and Sanseviero, Omar and Cameron, Glenn and Ballantyne, Ian and Black, Kat and Chen, Kaifeng and Wang, Weiyi and Li, Zhe and Martins, Gus and Lee, Jinhyuk and Sherwood, Mark and Ji, Juyeong and Wu, Renjie and Zheng, Jingxiao and Singh, Jyotinder and Sharma, Abheesht and Sreepat, Divya and Jain, Aashi and Elarabawy, Adham and Co, AJ and Doumanoglou, Andreas and Samari, Babak and Hora, Ben and Potetz, Brian and Kim, Dahun and Alfonseca, Enrique and Moiseev, Fedor and Han, Feng and Palma Gomez, Frank and Hernández Ábrego, Gustavo and Zhang, Hesen and Hui, Hui and Han, Jay and Gill, Karan and Chen, Ke and Chen, Koert and Shanbhogue, Madhuri and Boratko, Michael and Suganthan, Paul and Duddu, Sai Meher Karthik and Mariserla, Sandeep and Ariafar, Setareh and Zhang, Shanfeng and Zhang, Shijie and Baumgartner, Simon and Goenka, Sonam and Qiu, Steve and Dabral, Tanmaya and Walker, Trevor and Rao, Vikram and Khawaja, Waleed and Zhou, Wenlei and Ren, Xiaoqi and Xia, Ye and Chen, Yichang and Chen, Yi-Ting and Dong, Zhe and Ding, Zhongli and Visin, Francesco and Liu, Gaël and Zhang, Jiageng and Kenealy, Kathleen and Casbon, Michelle and Kumar, Ravin and Mesnard, Thomas and Gleicher, Zach and Brick, Cormac and Lacombe, Olivier and Roberts, Adam and Sung, Yunhsuan and Hoffmann, Raphael and Warkentin, Tris and Joulin, Armand and Duerig, Tom and Seyedhosseini, Mojtaba},
    publisher={Google DeepMind},
    year={2025},
    url={https://arxiv.org/abs/2509.20354}
}
```

### Usage

These model weights are designed to be used with [Sentence Transformers](https://www.sbert.net/), using the [Gemma 3](https://huggingface.co/docs/transformers/main/en/model_doc/gemma3) implementation from [Hugging Face Transformers](https://huggingface.co/docs/transformers/en/index) as the backbone.

First install the Sentence Transformers library:

```bash
pip install -U sentence-transformers
```

Then you can load this model and run inference.

```python
from sentence_transformers import SentenceTransformer

# Download from the 🤗 Hub
model = SentenceTransformer("google/embeddinggemma-300m")

# Run inference with queries and documents
query = "Which planet is known as the Red Planet?"
documents = [\
    "Venus is often called Earth's twin because of its similar size and proximity.",\
    "Mars, known for its reddish appearance, is often referred to as the Red Planet.",\
    "Jupiter, the largest planet in our solar system, has a prominent red spot.",\
    "Saturn, famous for its rings, is sometimes mistaken for the Red Planet."\
]
query_embeddings = model.encode_query(query)
document_embeddings = model.encode_document(documents)
print(query_embeddings.shape, document_embeddings.shape)
# (768,) (4, 768)

# Compute similarities to determine a ranking
similarities = model.similarity(query_embeddings, document_embeddings)
print(similarities)
# tensor([[0.3011, 0.6359, 0.4930, 0.4889]])
```

**NOTE**: EmbeddingGemma activations do not support `float16`. Please use `float32` or `bfloat16` as appropriate for your hardware.

## Model Data

### Training Dataset

This model was trained on a dataset of text data that includes a wide variety of sources totaling approximately 320 billion tokens. Here are the key components:

- **Web Documents**: A diverse collection of web text ensures the model is exposed to a broad range of linguistic styles, topics, and vocabulary. The training dataset includes content in over 100 languages.
- **Code and Technical Documents**: Exposing the model to code and technical documentation helps it learn the structure and patterns of programming languages and specialized scientific content, which improves its understanding of code and technical questions.
- **Synthetic and Task-Specific Data**: Synthetically training data helps to teach the model specific skills. This includes curated data for tasks like information retrieval, classification, and sentiment analysis, which helps to fine-tune its performance for common embedding applications.

The combination of these diverse data sources is crucial for training a powerful multilingual embedding model that can handle a wide variety of different tasks and data formats.

### Data Preprocessing

Here are the key data cleaning and filtering methods applied to the training data:

- CSAM Filtering: Rigorous CSAM (Child Sexual Abuse Material) filtering was applied at multiple stages in the data preparation process to ensure the exclusion of harmful and illegal content.
- Sensitive Data Filtering: As part of making Gemma pre-trained models safe and reliable, automated techniques were used to filter out certain personal information and other sensitive data from training sets.
- Additional methods: Filtering based on content quality and safety in line with [our policies](https://ai.google/static/documents/ai-responsibility-update-published-february-2025.pdf).

## Model Development

### Hardware

EmbeddingGemma was trained using the latest generation of [Tensor Processing Unit (TPU)](https://cloud.google.com/tpu/docs/intro-to-tpu) hardware (TPUv5e), for more details refer to the [Gemma 3 model card](https://ai.google.dev/gemma/docs/core/model_card_3).

### Software

Training was done using [JAX](https://github.com/jax-ml/jax) and [ML Pathways](https://blog.google/technology/ai/introducing-pathways-next-generation-ai-architecture/). For more details refer to the [Gemma 3 model card](https://ai.google.dev/gemma/docs/core/model_card_3).

## Evaluation

### Benchmark Results

The model was evaluated against a large collection of different datasets and metrics to cover different aspects of text understanding.

#### Full Precision Checkpoint

| **MTEB (Multilingual, v2)** |
| --- |
| **Dimensionality** | **Mean (Task)** | **Mean (TaskType)** |
| 768d | 61.15 | 54.31 |
| 512d | 60.71 | 53.89 |
| 256d | 59.68 | 53.01 |
| 128d | 58.23 | 51.77 |

| **MTEB (English, v2)** |
| --- |
| **Dimensionality** | **Mean (Task)** | **Mean (TaskType)** |
| 768d | 69.67 | 65.11 |
| 512d | 69.18 | 64.59 |
| 256d | 68.37 | 64.02 |
| 128d | 66.66 | 62.70 |

| **MTEB (Code, v1)** |
| --- |
| **Dimensionality** | **Mean (Task)** | **Mean (TaskType)** |
| 768d | 68.76 | 68.76 |
| 512d | 68.48 | 68.48 |
| 256d | 66.74 | 66.74 |
| 128d | 62.96 | 62.96 |

#### QAT Checkpoints

| **MTEB (Multilingual, v2)** |
| --- |
| **Quant config (dimensionality)** | **Mean (Task)** | **Mean (TaskType)** |
| Q4\_0 (768d) | 60.62 | 53.61 |
| Q8\_0 (768d) | 60.93 | 53.95 |
| Mixed Precision\* (768d) | 60.69 | 53.82 |

| **MTEB (English, v2)** |
| --- |
| **Quant config (dimensionality)** | **Mean (Task)** | **Mean (TaskType)** |
| Q4\_0 (768d) | 69.31 | 64.65 |
| Q8\_0 (768d) | 69.49 | 64.84 |
| Mixed Precision\* (768d) | 69.32 | 64.82 |

| **MTEB (Code, v1)** |
| --- |
| **Quant config (dimensionality)** | **Mean (Task)** | **Mean (TaskType)** |
| Q4\_0 (768d) | 67.99 | 67.99 |
| Q8\_0 (768d) | 68.70 | 68.70 |
| Mixed Precision\* (768d) | 68.03 | 68.03 |

Note: QAT models are evaluated after quantization

\\* Mixed Precision refers to per-channel quantization with int4 for embeddings, feedforward, and projection layers, and int8 for attention (e4\_a8\_f4\_p4).

### Prompt Instructions

EmbeddingGemma can generate optimized embeddings for various use cases—such as document retrieval, question answering, and fact verification—or for specific input types—either a query or a document—using prompts that are prepended to the input strings.
Query prompts follow the form `task: {task description} | query:` where the task description varies by the use case, with the default task description being `search result`. Document-style prompts follow the form `title: {title | "none"} | text:` where the title is either `none` (the default) or the actual title of the document. Note that providing a title, if available, will improve model performance for document prompts but may require manual formatting.

Use the following prompts based on your use case and input data type. These may already be available in the EmbeddingGemma configuration in your modeling framework of choice.

| **Use Case (task type enum)** | **Descriptions** | **Recommended Prompt** |
| --- | --- | --- |
| Retrieval (Query) | Used to generate embeddings that are optimized for document search or information retrieval | task: search result \| query: {content} |
| Retrieval (Document) | title: {title \| "none"} \| text: {content} |
| Question Answering | task: question answering \| query: {content} |
| Fact Verification | task: fact checking \| query: {content} |
| Classification | Used to generate embeddings that are optimized to classify texts according to preset labels | task: classification \| query: {content} |
| Clustering | Used to generate embeddings that are optimized to cluster texts based on their similarities | task: clustering \| query: {content} |
| Semantic Similarity | Used to generate embeddings that are optimized to assess text similarity. This is not intended for retrieval use cases. | task: sentence similarity \| query: {content} |
| Code Retrieval | Used to retrieve a code block based on a natural language query, such as _sort an array_ or _reverse a linked list_. Embeddings of the code blocks are computed using retrieval\_document. | task: code retrieval \| query: {content} |

## Usage and Limitations

These models have certain limitations that users should be aware of.

### Intended Usage

Open embedding models have a wide range of applications across various industries and domains. The following list of potential uses is not comprehensive. The purpose of this list is to provide contextual information about the possible use-cases that the model creators considered as part of model training and development.

- **Semantic Similarity**: Embeddings optimized to assess text similarity, such as recommendation systems and duplicate detection

- **Classification**: Embeddings optimized to classify texts according to preset labels, such as sentiment analysis and spam detection

- **Clustering**: Embeddings optimized to cluster texts based on their similarities, such as document organization, market research, and anomaly detection

- **Retrieval**

  - **Document**: Embeddings optimized for document search, such as indexing articles, books, or web pages for search
  - **Query**: Embeddings optimized for general search queries, such as custom search
  - **Code Query**: Embeddings optimized for retrieval of code blocks based on natural language queries, such as code suggestions and search
- **Question Answering**: Embeddings for questions in a question-answering system, optimized for finding documents that answer the question, such as chatbox.

- **Fact Verification**: Embeddings for statements that need to be verified, optimized for retrieving documents that contain evidence supporting or refuting the statement, such as automated fact-checking systems.


### Limitations

- Training Data

  - The quality and diversity of the training data significantly influence the model's capabilities. Biases or gaps in the training data can lead to limitations in the model's responses.
  - The scope of the training dataset determines the subject areas the model can handle effectively.
- Language Ambiguity and Nuance

  - Natural language is inherently complex. Models might struggle to grasp subtle nuances, sarcasm, or figurative language.

### Ethical Considerations and Risks

Risks identified and mitigations:

- **Perpetuation of biases**: It's encouraged to perform continuous monitoring (using evaluation metrics, human review) and the exploration of de-biasing techniques during model training, fine-tuning, and other use cases.
- **Misuse for malicious purposes**: Technical limitations and developer and end-user education can help mitigate against malicious applications of embeddings. Educational resources and reporting mechanisms for users to flag misuse are provided. Prohibited uses of Gemma models are outlined in the [Gemma Prohibited Use Policy](https://ai.google.dev/gemma/prohibited_use_policy).
- **Privacy violations**: Models were trained on data filtered for removal of certain personal information and other sensitive data. Developers are encouraged to adhere to privacy regulations with privacy-preserving techniques.

### Benefits

At the time of release, this family of models provides high-performance open embedding model implementations designed from the ground up for responsible AI development compared to similarly sized models. Using the benchmark evaluation metrics described in this document, these models have shown superior performance to other, comparably-sized open model alternatives.

Downloads last month1,245,465

Safetensors

Model size

0.3B params

Tensor type

F32

·

Files info

Inference Providers [NEW](https://huggingface.co/docs/inference-providers)

HF Inference API

[Sentence Similarity](https://huggingface.co/tasks/sentence-similarity "Learn more about sentence-similarity")

Examples

Source SentenceSentences to compare toAdd SentenceGenerate

View Code Snippets

Maximize

## Model tree for google/embeddinggemma-300m

Adapters

[8 models](https://huggingface.co/models?other=base_model:adapter:google/embeddinggemma-300m)

Finetunes

[230 models](https://huggingface.co/models?other=base_model:finetune:google/embeddinggemma-300m)

Quantizations

[43 models](https://huggingface.co/models?other=base_model:quantized:google/embeddinggemma-300m)

## Spaces using google/embeddinggemma-300m100

[![](https://cdn-avatars.huggingface.co/v1/production/uploads/5dd96eb166059660ed1ee413/WtA3YYitedOr9n02eHfJe.png)\\
\\
google/mood-palette](https://huggingface.co/spaces/google/mood-palette) [![](https://cdn-avatars.huggingface.co/v1/production/uploads/5dd96eb166059660ed1ee413/WtA3YYitedOr9n02eHfJe.png)\\
\\
google/embeddinggemma-tuning-lab](https://huggingface.co/spaces/google/embeddinggemma-tuning-lab) [🥇\\
\\
mteb/leaderboard](https://huggingface.co/spaces/mteb/leaderboard) [⚡\\
\\
jairwaal/image](https://huggingface.co/spaces/jairwaal/image) [⚡\\
\\
Jakob08/moneychatbot](https://huggingface.co/spaces/Jakob08/moneychatbot) [🕸️\\
\\
kdcyberdude/HARvestGym](https://huggingface.co/spaces/kdcyberdude/HARvestGym) [🥇\\
\\
maxpar1/leaderboard](https://huggingface.co/spaces/maxpar1/leaderboard) [🦁\\
\\
govtech/lionguard-demo](https://huggingface.co/spaces/govtech/lionguard-demo) \+ 95 Spaces\+ 92 Spaces

## Collections including google/embeddinggemma-300m

[**Google's Gemma models family**\\
\\
Collection\\
\\
334 items•Updated Mar 12• 798](https://huggingface.co/collections/google/googles-gemma-models-family)

[**EmbeddingGemma**\\
\\
Collection\\
\\
3 items•Updated Mar 12• 117](https://huggingface.co/collections/google/embeddinggemma)

## Paper for google/embeddinggemma-300m

[**EmbeddingGemma: Powerful and Lightweight Text Representations**\\
Paper • 2509.20354 •Published Sep 24, 2025• 49](https://huggingface.co/papers/2509.20354)

## Evaluation results

- ArguAna Default Teston [mteb/arguana](https://huggingface.co/datasets/mteb/arguana) [View evaluation results](https://huggingface.co/google/embeddinggemma-300m/discussions/42) [![](https://cdn-avatars.huggingface.co/v1/production/uploads/5ff5943752c26e9bc240bada/OrZxdlg8doDNO2TZ6Q58G.png)\\
source](https://github.com/embeddings-benchmark/mteb/) [leaderboard](https://huggingface.co/datasets/mteb/arguana?eval_result=google/embeddinggemma-300m)


71.54 \*

- ArguAnaon [mteb/arguana](https://huggingface.co/datasets/mteb/arguana) [View evaluation results](https://huggingface.co/google/embeddinggemma-300m/discussions/42) [![](https://cdn-avatars.huggingface.co/v1/production/uploads/5ff5943752c26e9bc240bada/OrZxdlg8doDNO2TZ6Q58G.png)\\
source](https://github.com/embeddings-benchmark/mteb/) [leaderboard](https://huggingface.co/datasets/mteb/arguana?eval_result=google/embeddinggemma-300m)


71.54 \*


System theme

Company

[TOS](https://huggingface.co/terms-of-service) [Privacy](https://huggingface.co/privacy) [About](https://huggingface.co/huggingface) [Careers](https://apply.workable.com/huggingface/)  [Hugging Face](https://huggingface.co/)

Website

[Models](https://huggingface.co/models) [Datasets](https://huggingface.co/datasets) [Spaces](https://huggingface.co/spaces) [Pricing](https://huggingface.co/pricing) [Docs](https://huggingface.co/docs)

StripeM-Inner

You have to accept the conditions to access the files info

Inference providers allow you to run inference using different serverless providers.

View evaluation results
shared by the community

Source: Obtained using MTEB v1.34.7
by mteb

Obtained using MTEB v1.34.7

View evaluation results
shared by the community

Source: Obtained using MTEB v1.34.7
by mteb

Obtained using MTEB v1.34.7

## Run 15,000+ Models Instantly

Inference Providers let you run inference on thousands of models served by our partners using a simple,
unified, OpenAI-compatible serverless API ( [Learn more](https://huggingface.co/docs/inference-providers)).

google/embeddinggemma-300m is supported by the following Inference Providers:

HF Inference API

View API CodeDismiss