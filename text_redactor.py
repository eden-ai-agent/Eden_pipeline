from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
from presidio_analyzer.nlp_engine import SpacyNlpEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig
import spacy
import logging
from typing import List, Dict, Tuple, Optional, Any
import json
import re
from dataclasses import dataclass
from enum import Enum

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RedactionMode(Enum):
    """Different modes for redacting PII."""
    REPLACE = "replace"  # Replace with <ENTITY_TYPE>
    MASK = "mask"       # Replace with asterisks
    HASH = "hash"       # Replace with hash value
    CUSTOM = "custom"   # Use custom replacement values
    KEEP = "keep"       # Keep original (for allowlisted entities)

@dataclass
class PIIEntity:
    """Represents a detected PII entity with metadata."""
    text: str
    entity_type: str
    start: int
    end: int
    score: float
    redacted_value: Optional[str] = None

class TextRedactor:
    """
    Advanced text redaction system using Microsoft Presidio.
    
    Supports multiple redaction modes, custom operators, entity allowlisting,
    and comprehensive PII detection with detailed reporting.
    """
    
    def __init__(self, 
                 spacy_model_name: str = "en_core_web_sm",
                 default_mode: RedactionMode = RedactionMode.REPLACE,
                 min_confidence: float = 0.5,
                 supported_languages: List[str] = None):
        """
        Initialize the TextRedactor.
        
        Args:
            spacy_model_name: SpaCy model to use for NLP
            default_mode: Default redaction mode
            min_confidence: Minimum confidence score for PII detection
            supported_languages: List of supported languages
        """
        self.spacy_model_name = spacy_model_name
        self.default_mode = default_mode
        self.min_confidence = min_confidence
        self.supported_languages = supported_languages or ["en"]
        
        # Custom operators for different redaction modes
        self.operators = {
            RedactionMode.REPLACE: {},  # Default behavior
            RedactionMode.MASK: {},
            RedactionMode.HASH: {},
            RedactionMode.CUSTOM: {},
            RedactionMode.KEEP: {}
        }
        
        # Entity allowlist - entities that should not be redacted
        self.allowlisted_entities: Dict[str, List[str]] = {}
        
        # Custom replacement values
        self.custom_replacements: Dict[str, str] = {
            "PERSON": "[PERSON]",
            "EMAIL_ADDRESS": "[EMAIL]",
            "PHONE_NUMBER": "[PHONE]",
            "CREDIT_CARD": "[CARD]",
            "IBAN_CODE": "[IBAN]",
            "IP_ADDRESS": "[IP]",
            "LOCATION": "[LOCATION]",
            "DATE_TIME": "[DATE]",
            "MEDICAL_LICENSE": "[MEDICAL_ID]",
            "US_SSN": "[SSN]",
            "US_DRIVER_LICENSE": "[LICENSE]"
        }
        
        self._initialize_engines()
        self._setup_operators()
    
    def _initialize_engines(self) -> None:
        """Initialize Presidio analyzer and anonymizer engines."""
        try:
            # Try to load spaCy model
            spacy.load(self.spacy_model_name)
            nlp_engine = SpacyNlpEngine(models={self.spacy_model_name: self.spacy_model_name})
            self.analyzer = AnalyzerEngine(
                nlp_engine=nlp_engine, 
                supported_languages=self.supported_languages
            )
            logger.info(f"Initialized with spaCy model: {self.spacy_model_name}")
            
        except OSError:
            logger.warning(f"spaCy model '{self.spacy_model_name}' not found. Using default recognizers.")
            self.analyzer = AnalyzerEngine(supported_languages=self.supported_languages)
        
        self.anonymizer = AnonymizerEngine()
    
    def _setup_operators(self) -> None:
        """Setup custom operators for different redaction modes."""
        # Setup mask operator
        for entity_type in self.custom_replacements.keys():
            self.operators[RedactionMode.MASK][entity_type] = OperatorConfig(
                "mask", {"chars_to_mask": -1, "masking_char": "*", "from_end": False}
            )
            
            self.operators[RedactionMode.HASH][entity_type] = OperatorConfig(
                "hash", {"hash_type": "sha256"}
            )
            
            self.operators[RedactionMode.CUSTOM][entity_type] = OperatorConfig(
                "replace", {"new_value": self.custom_replacements[entity_type]}
            )
            
            self.operators[RedactionMode.KEEP][entity_type] = OperatorConfig(
                "keep", {}
            )
    
    def add_allowlisted_entity(self, entity_type: str, entity_value: str) -> None:
        """
        Add an entity to the allowlist (won't be redacted).
        
        Args:
            entity_type: Type of entity (e.g., "PERSON")
            entity_value: Specific value to allowlist (e.g., "John Public")
        """
        if entity_type not in self.allowlisted_entities:
            self.allowlisted_entities[entity_type] = []
        self.allowlisted_entities[entity_type].append(entity_value.lower())
    
    def set_custom_replacement(self, entity_type: str, replacement: str) -> None:
        """
        Set custom replacement value for an entity type.
        
        Args:
            entity_type: PII entity type
            replacement: Custom replacement text
        """
        self.custom_replacements[entity_type] = replacement
        self.operators[RedactionMode.CUSTOM][entity_type] = OperatorConfig(
            "replace", {"new_value": replacement}
        )
    
    def _is_allowlisted(self, entity_text: str, entity_type: str) -> bool:
        """Check if an entity is in the allowlist."""
        if entity_type not in self.allowlisted_entities:
            return False
        return entity_text.lower() in self.allowlisted_entities[entity_type]
    
    def _filter_results_by_confidence(self, results: List[Any]) -> List[Any]:
        """Filter analyzer results by minimum confidence score."""
        return [result for result in results if result.score >= self.min_confidence]
    
    def _filter_allowlisted_entities(self, text: str, results: List[Any]) -> List[Any]:
        """Remove allowlisted entities from analyzer results."""
        filtered_results = []
        for result in results:
            entity_text = text[result.start:result.end]
            if not self._is_allowlisted(entity_text, result.entity_type):
                filtered_results.append(result)
            else:
                logger.debug(f"Skipping allowlisted entity: {entity_text} ({result.entity_type})")
        return filtered_results
    
    def redact_text(self, 
                   text_to_redact: str, 
                   language: str = "en",
                   mode: Optional[RedactionMode] = None,
                   entity_types: Optional[List[str]] = None) -> Tuple[str, List[PIIEntity]]:
        """
        Redact PII from text with flexible options.
        
        Args:
            text_to_redact: Input text to redact
            language: Language of the text
            mode: Redaction mode to use
            entity_types: Specific entity types to redact (None for all)
            
        Returns:
            Tuple of (redacted_text, list_of_pii_entities)
        """
        if not text_to_redact or not text_to_redact.strip():
            return "", []
        
        mode = mode or self.default_mode
        
        try:
            # Analyze text for PII
            analyzer_results = self.analyzer.analyze(
                text=text_to_redact, 
                language=language,
                entities=entity_types
            )
            
            # Filter by confidence and allowlist
            analyzer_results = self._filter_results_by_confidence(analyzer_results)
            analyzer_results = self._filter_allowlisted_entities(text_to_redact, analyzer_results)
            
            # Sort by start position (important for proper anonymization)
            analyzer_results.sort(key=lambda x: x.start)
            
            # Apply anonymization based on mode
            if mode == RedactionMode.REPLACE:
                anonymized_result = self.anonymizer.anonymize(
                    text=text_to_redact,
                    analyzer_results=analyzer_results
                )
            else:
                # Use custom operators
                operators = self.operators[mode]
                anonymized_result = self.anonymizer.anonymize(
                    text=text_to_redact,
                    analyzer_results=analyzer_results,
                    operators=operators
                )
            
            # Create PII entity objects with metadata
            pii_entities = []
            redacted_text = anonymized_result.text
            
            for result in analyzer_results:
                entity = PIIEntity(
                    text=text_to_redact[result.start:result.end],
                    entity_type=result.entity_type,
                    start=result.start,
                    end=result.end,
                    score=result.score
                )
                
                # Try to find what it was replaced with
                if mode != RedactionMode.KEEP:
                    entity.redacted_value = self._find_redacted_value(
                        entity, mode, redacted_text
                    )
                
                pii_entities.append(entity)
            
            return redacted_text, pii_entities
            
        except Exception as e:
            logger.error(f"Error during text redaction: {e}")
            return text_to_redact, []
    
    def _find_redacted_value(self, entity: PIIEntity, mode: RedactionMode, redacted_text: str) -> str:
        """Attempt to find what value replaced the original entity."""
        if mode == RedactionMode.REPLACE:
            return f"<{entity.entity_type}>"
        elif mode == RedactionMode.CUSTOM:
            return self.custom_replacements.get(entity.entity_type, f"[{entity.entity_type}]")
        elif mode == RedactionMode.MASK:
            return "*" * len(entity.text)
        elif mode == RedactionMode.HASH:
            return "[HASHED]"  # Actual hash would be computed by Presidio
        return "[REDACTED]"
    
    def analyze_text(self, text: str, language: str = "en") -> List[PIIEntity]:
        """
        Analyze text for PII without redacting.
        
        Args:
            text: Text to analyze
            language: Language of the text
            
        Returns:
            List of detected PII entities
        """
        if not text or not text.strip():
            return []
        
        try:
            analyzer_results = self.analyzer.analyze(text=text, language=language)
            analyzer_results = self._filter_results_by_confidence(analyzer_results)
            
            return [
                PIIEntity(
                    text=text[result.start:result.end],
                    entity_type=result.entity_type,
                    start=result.start,
                    end=result.end,
                    score=result.score
                )
                for result in analyzer_results
            ]
            
        except Exception as e:
            logger.error(f"Error during text analysis: {e}")
            return []
    
    def get_supported_entities(self) -> List[str]:
        """Get list of supported PII entity types."""
        registry = RecognizerRegistry()
        recognizers = registry.get_recognizers(language="en")
        entities = set()
        for recognizer in recognizers:
            entities.update(recognizer.supported_entities)
        return sorted(list(entities))
    
    def batch_redact(self, 
                    texts: List[str], 
                    language: str = "en",
                    mode: Optional[RedactionMode] = None) -> List[Tuple[str, List[PIIEntity]]]:
        """
        Redact multiple texts in batch.
        
        Args:
            texts: List of texts to redact
            language: Language of the texts
            mode: Redaction mode to use
            
        Returns:
            List of (redacted_text, pii_entities) tuples
        """
        results = []
        for text in texts:
            redacted, entities = self.redact_text(text, language, mode)
            results.append((redacted, entities))
        return results
    
    def generate_report(self, pii_entities: List[PIIEntity]) -> Dict[str, Any]:
        """
        Generate a summary report of detected PII.
        
        Args:
            pii_entities: List of detected PII entities
            
        Returns:
            Dictionary containing PII statistics
        """
        if not pii_entities:
            return {"total_entities": 0, "entity_types": {}, "risk_level": "low"}
        
        entity_counts = {}
        confidence_scores = []
        
        for entity in pii_entities:
            entity_type = entity.entity_type
            entity_counts[entity_type] = entity_counts.get(entity_type, 0) + 1
            confidence_scores.append(entity.score)
        
        avg_confidence = sum(confidence_scores) / len(confidence_scores)
        
        # Simple risk assessment
        risk_level = "low"
        if len(pii_entities) > 10 or avg_confidence > 0.9:
            risk_level = "high"
        elif len(pii_entities) > 5 or avg_confidence > 0.7:
            risk_level = "medium"
        
        return {
            "total_entities": len(pii_entities),
            "entity_types": entity_counts,
            "average_confidence": avg_confidence,
            "risk_level": risk_level,
            "high_confidence_entities": len([e for e in pii_entities if e.score > 0.8])
        }

# Demo and testing
def run_comprehensive_demo():
    """Run a comprehensive demonstration of the enhanced text redactor."""
    print("=== Enhanced Text Redactor Demo ===\n")
    
    # Initialize redactor
    redactor = TextRedactor(min_confidence=0.6)
    
    # Add some allowlisted entities
    redactor.add_allowlisted_entity("PERSON", "John Public")  # This won't be redacted
    redactor.set_custom_replacement("EMAIL_ADDRESS", "[REDACTED_EMAIL]")
    
    print(f"Supported entities: {redactor.get_supported_entities()}")
    print()
    
    # Test cases with different scenarios
    test_cases = [
        {
            "text": "My name is John Doe and my email is john.doe@company.com. Call me at 555-0123.",
            "description": "Basic PII test"
        },
        {
            "text": "Contact John Public at john.public@example.com for more information.",
            "description": "Allowlisted person test"
        },
        {
            "text": "Patient ID: P123456, DOB: 1990-05-15, SSN: 123-45-6789, Insurance: Blue Cross",
            "description": "Healthcare PII test"
        },
        {
            "text": "Meeting scheduled for 2024-03-15 at 123 Main Street, New York, NY 10001",
            "description": "Location and date test"
        },
        {
            "text": "No sensitive information in this text.",
            "description": "Clean text test"
        }
    ]
    
    # Test different redaction modes
    modes = [RedactionMode.REPLACE, RedactionMode.MASK, RedactionMode.CUSTOM, RedactionMode.HASH]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"--- Test Case {i}: {test_case['description']} ---")
        print(f"Original: {test_case['text']}")
        
        for mode in modes:
            redacted_text, pii_entities = redactor.redact_text(
                test_case['text'], 
                mode=mode
            )
            
            print(f"{mode.value.upper():8}: {redacted_text}")
            
            if mode == RedactionMode.REPLACE and pii_entities:  # Show details only once
                print("Detected PII:")
                for entity in pii_entities:
                    print(f"  - '{entity.text}' -> {entity.entity_type} (confidence: {entity.score:.2f})")
        
        print()
    
    # Demonstrate batch processing
    print("--- Batch Processing Demo ---")
    batch_texts = [
        "Email me at user1@example.com",
        "Call John Smith at (555) 123-4567",
        "Meeting at 456 Oak Street tomorrow"
    ]
    
    batch_results = redactor.batch_redact(batch_texts, mode=RedactionMode.CUSTOM)
    for i, (redacted, entities) in enumerate(batch_results):
        print(f"Batch {i+1}: {redacted} ({len(entities)} PII entities)")
    
    # Generate comprehensive report
    print("\n--- PII Analysis Report ---")
    all_entities = []
    for text_case in test_cases:
        entities = redactor.analyze_text(text_case['text'])
        all_entities.extend(entities)
    
    report = redactor.generate_report(all_entities)
    print(f"Report: {json.dumps(report, indent=2)}")

if __name__ == '__main__':
    try:
        run_comprehensive_demo()
    except Exception as e:
        logger.error(f"Demo failed: {e}")
        raise