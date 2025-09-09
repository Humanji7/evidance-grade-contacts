"""
Демонстрационный integration тест для EGC PoC.

Показывает разницу с unit тестами - тестирует реальные сайты end-to-end.

Использование:
    # Тест на URL из gold dataset (по умолчанию)
    EGC_RUN_INTEGRATION=1 pytest tests/integration/test_demo.py -v
    
    # Тест на ваш URL
    EGC_TEST_URL="https://example.com/team" EGC_RUN_INTEGRATION=1 pytest tests/integration/test_demo.py -v

Требования:
    - EGC_RUN_INTEGRATION=1 (защита от случайного запуска)
    - Playwright browsers установлены
"""

import os
import pytest
from src.pipeline.ingest import IngestPipeline


@pytest.mark.skipif(
    os.getenv("EGC_RUN_INTEGRATION") != "1",
    reason="Integration tests require EGC_RUN_INTEGRATION=1"
)
def test_end_to_end_contact_extraction():
    """
    Integration тест: извлекает контакты с реального сайта end-to-end.
    
    В отличие от unit тестов:
    - Делает реальные HTTP запросы
    - Может использовать Playwright для обхода защит
    - Тестирует полный pipeline от URL до готовых контактов
    - Проверяет что все 7 полей evidence package присутствуют
    """
    # Гибкий URL: можете задать свой через EGC_TEST_URL
    test_url = os.getenv(
        "EGC_TEST_URL", 
        "https://www.jacksonlewis.com/people/jacqueline-a-scott"  # Известно работает
    )
    
    print(f"\n🌐 Testing URL: {test_url}")
    
    # Создаём pipeline и запускаем полное извлечение
    pipeline = IngestPipeline()
    result = pipeline.ingest(test_url)
    
    # Проверки успешности
    assert result.success, f"Failed to ingest {test_url}: {result.error}"
    assert len(result.contacts) > 0, "No contacts extracted"
    
    print(f"✅ Extraction method: {result.method}")
    print(f"📞 Contacts found: {len(result.contacts)}")
    
    # Проверяем качество каждого контакта
    verified_count = 0
    for i, contact in enumerate(result.contacts):
        print(f"\n📋 Contact #{i+1}: {contact.person_name} ({contact.contact_type})")
        
        if contact.verification_status == "VERIFIED":
            verified_count += 1
            
            # Проверяем полноту evidence package (все 7 полей)
            evidence = contact.evidence
            assert evidence.source_url, "Missing source_url in evidence"
            assert evidence.selector_or_xpath, "Missing selector_or_xpath in evidence"
            assert evidence.verbatim_quote, "Missing verbatim_quote in evidence"
            assert evidence.dom_node_screenshot, "Missing dom_node_screenshot in evidence"
            assert evidence.timestamp, "Missing timestamp in evidence"
            assert evidence.parser_version, "Missing parser_version in evidence"
            assert evidence.content_hash, "Missing content_hash in evidence"
            
            print(f"   ✅ Complete evidence package (7/7 fields)")
        else:
            print(f"   ⚠️  Status: {contact.verification_status}")
    
    # Проверяем что есть хотя бы один VERIFIED контакт
    assert verified_count > 0, "No VERIFIED contacts found"
    
    success_rate = (verified_count / len(result.contacts)) * 100
    print(f"\n📈 Success Rate: {success_rate:.1f}% ({verified_count}/{len(result.contacts)})")
    
    # Для PoC ожидаем разумный success rate
    assert success_rate >= 50, f"Success rate too low: {success_rate:.1f}%"
    
    print(f"🎯 Integration test passed! URL successfully processed end-to-end.")


if __name__ == "__main__":
    # Удобный запуск для разработки
    if os.getenv("EGC_RUN_INTEGRATION") == "1":
        test_end_to_end_contact_extraction()
    else:
        print("Set EGC_RUN_INTEGRATION=1 to run integration test")
