from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
from presidio_analyzer.nlp_engine import SpacyNlpEngine
from presidio_anonymizer import AnonymizerEngine
# Entities are not strictly needed for basic anonymization with defaults,
# but good to have for more complex configurations.
# from presidio_anonymizer.entities import RecognizerResult, OperatorConfig
import spacy

class TextRedactor:
    def __init__(self, spacy_model_name="en_core_web_sm"):
        """
        Initializes the TextRedactor with Presidio Analyzer and Anonymizer.
        Tries to load a spaCy model for NER.
        """
        try:
            # Try to load the spaCy model to ensure it's available
            spacy.load(spacy_model_name)
            nlp_engine = SpacyNlpEngine(models={spacy_model_name: spacy_model_name})
            self.analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])
            print(f"TextRedactor initialized with spaCy model: {spacy_model_name}")
        except OSError:
            print(f"Warning: spaCy model '{spacy_model_name}' not found or failed to load.")
            print("Presidio Analyzer will use its default set of recognizers, which might be less comprehensive.")
            # Fallback to default AnalyzerEngine without specific spaCy model if loading fails
            self.analyzer = AnalyzerEngine()

        self.anonymizer = AnonymizerEngine()

    def redact_text(self, text_to_redact, language="en"):
        """
        Redacts PII from the given text.

        :param text_to_redact: The input string.
        :param language: Language of the text (default "en").
        :return: A tuple containing the redacted text string and a list of PII entities found.
        """
        if not text_to_redact or not text_to_redact.strip():
            return "", []

        try:
            analyzer_results = self.analyzer.analyze(text=text_to_redact, language=language)

            # Default anonymization replaces PII with <ENTITY_TYPE>
            # Example: "John Doe" becomes "<PERSON>"
            anonymized_result = self.anonymizer.anonymize(
                text=text_to_redact,
                analyzer_results=analyzer_results
            )

            # For metadata, we can extract details about what was found and redacted
            pii_entities = []
            for result in analyzer_results:
                pii_entities.append({
                    "text": text_to_redact[result.start:result.end],
                    "entity_type": result.entity_type,
                    "start": result.start,
                    "end": result.end,
                    "score": result.score
                })

            return anonymized_result.text, pii_entities

        except Exception as e:
            print(f"Error during text redaction: {e}")
            # Return original text and empty list if redaction fails
            return text_to_redact, []

if __name__ == '__main__':
    print("Initializing TextRedactor for testing...")
    # This might take a moment on first run if spaCy model components are being fully loaded by Presidio
    redactor = TextRedactor()
    print("TextRedactor initialized.")

    sample_texts = [
        "My name is John Doe and my phone number is 212-555-1234.",
        "Please contact Jane Smith at jsmith@example.com or call her at (987) 654-3210.",
        "The meeting is scheduled for next Friday with Mr. Robert Brown.",
        "He lives at 123 Main St, Anytown, USA.",
        "No PII here.",
        "", # Empty string
        "   ", # Whitespace only
        "Dr. Emily White's email is emily.white@healthcorp.org and her patient ID is HC12345."
    ]

    for i, text in enumerate(sample_texts):
        print(f"\n--- Test Case {i+1} ---")
        print(f"Original Text: '{text}'")
        redacted_text, pii_details = redactor.redact_text(text)
        print(f"Redacted Text: '{redacted_text}'")
        if pii_details:
            print("PII Detected:")
            for pii in pii_details:
                print(f"  - Text: '{pii['text']}', Type: {pii['entity_type']}, Score: {pii['score']:.2f}")
        else:
            print("No PII detected or redaction failed.")

    # Example of a different language (if models are available for it in Presidio)
    # For now, Presidio's default recognizers are mainly for English.
    # text_es = "Mi nombre es Juan Pérez y mi email es juan.perez@example.com."
    # print("\n--- Spanish Test Case ---")
    # print(f"Original ES: '{text_es}'")
    # redacted_es, pii_es = redactor.redact_text(text_es, language="es") # Might not work well without Spanish model
    # print(f"Redacted ES: '{redacted_es}'")

    # Example of using custom anonymization (not part of this subtask's core reqs but for info)
    # from presidio_anonymizer.entities import OperatorConfig
    # anonymized_custom = redactor.anonymizer.anonymize(
    #     text="My name is Test User.",
    #     analyzer_results=redactor.analyzer.analyze(text="My name is Test User.", language="en"),
    #     operators={"PERSON": OperatorConfig("replace", {"new_value": "[REDACTED PERSON]"})}
    # )
    # print(f"\nCustom Redaction: '{anonymized_custom.text}'")
