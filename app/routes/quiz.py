# app/quiz.py
from fastapi import APIRouter, HTTPException
from groq import Groq, BadRequestError
import os
import re
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# Initialize Groq client
try:
    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
except Exception as e:
    logger.error(f"Failed to initialize Groq client: {str(e)}")
    groq_client = None

@router.post("/generate-mcqs")
async def generate_mcqs(data: dict):
    topic = data.get("topic")
    num_questions = data.get("num_questions", 5)
    
    # Validate input
    if not topic or not isinstance(topic, str):
        raise HTTPException(
            status_code=400, 
            detail="Topic is required and must be a string"
        )
    
    if not isinstance(num_questions, int) or num_questions < 1 or num_questions > 20:
        raise HTTPException(
            status_code=400, 
            detail="Number of questions must be an integer between 1 and 20"
        )
    
    if not groq_client:
        raise HTTPException(
            status_code=503,
            detail="Quiz service is currently unavailable"
        )
    
    try:
        # Generate MCQs using Groq API with more specific instructions
        response = groq_client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert quiz generator. Generate multiple-choice questions with exactly 4 options each. "
                        "For each question, provide:\n"
                        "1. A clear question\n"
                        "2. Four distinct options labeled A), B), C), D)\n"
                        "3. The correct answer letter (A, B, C, or D)\n"
                        "4. A brief explanation\n\n"
                        "Format each question EXACTLY as shown below:\n\n"
                        "Q1: [Question text here]\n"
                        "A) [Option A text]\n"
                        "B) [Option B text]\n"
                        "C) [Option C text]\n"
                        "D) [Option D text]\n"
                        "Answer: [Correct letter]\n"
                        "Explanation: [Explanation text]\n\n"
                        "Important rules:\n"
                        "- Only use A, B, C, D for answer letters\n"
                        "- Keep explanations concise (1-2 sentences)\n"
                        "- Ensure answers are factually correct\n"
                        "- Separate questions with two newlines"
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"Generate {num_questions} MCQs about the topic: {topic}.\n"
                        "Follow the format precisely. Do not include any additional text."
                    )
                }
            ],
            temperature=0.3,  # Lower temperature for more factual accuracy
            max_tokens=4000,
            stop=["Q" + str(num_questions + 1) + ":"],  # Stop after last question
            top_p=0.9
        )
        
        # Parse the response
        content = response.choices[0].message.content
        logger.debug(f"Raw Groq response:\n{content}")
        questions = parse_mcqs(content)
        
        if len(questions) < num_questions:
            logger.warning(
                f"Requested {num_questions} questions but only parsed {len(questions)}. "
                f"Content:\n{content}"
            )
        
        # Validate answer format
        for i, q in enumerate(questions):
            if q["answer"] not in ["A", "B", "C", "D"]:
                logger.error(f"Invalid answer format in question {i+1}: {q['answer']}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Invalid answer format in generated question {i+1}"
                )
        
        return {"questions": questions}
    
    except BadRequestError as e:
        logger.error(f"Groq API bad request: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid request to quiz service")
    
    except Exception as e:
        logger.exception("Failed to generate MCQs")
        raise HTTPException(
            status_code=500, 
            detail=f"Quiz generation failed: {str(e)}"
        )

def parse_mcqs(content: str):
    questions = []
    # Split into question blocks (separated by 2+ newlines)
    blocks = re.split(r'\n\s*\n', content.strip())
    
    for block in blocks:
        if not block.strip():
            continue
            
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if len(lines) < 6:  # Minimum lines: Q, A, B, C, D, Answer
            continue
            
        q_data = {
            "question": "",
            "options": [],
            "answer": "",
            "explanation": ""
        }
        option_pattern = re.compile(r'^([A-D])\)\s*(.+)')
        answer_pattern = re.compile(r'^Answer:\s*([A-D])$', re.IGNORECASE)
        explanation_pattern = re.compile(r'^Explanation:\s*(.+)$', re.IGNORECASE)
        
        try:
            # First line should be question
            if lines[0].startswith("Q"):
                q_data["question"] = lines[0].split(":", 1)[1].strip()
            else:
                continue
                
            # Next 4 lines should be options
            for i in range(1, 5):
                match = option_pattern.match(lines[i])
                if match:
                    option_letter, option_text = match.groups()
                    q_data["options"].append(option_text)
                else:
                    break
                    
            if len(q_data["options"]) != 4:
                continue
                
            # Answer line
            answer_match = answer_pattern.match(lines[5])
            if answer_match:
                q_data["answer"] = answer_match.group(1).upper()
            else:
                continue
                
            # Explanation (might be on same line or next)
            explanation_line = lines[5] if explanation_pattern.match(lines[5]) else lines[6] if len(lines) > 6 else ""
            explanation_match = explanation_pattern.match(explanation_line)
            if explanation_match:
                q_data["explanation"] = explanation_match.group(1)
            
            questions.append(q_data)
            
        except Exception as e:
            logger.warning(f"Error parsing block: {str(e)}\nBlock content:\n{block}")
            continue
    
    return questions