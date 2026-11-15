import io,unittest
from unittest.mock import patch
from mara.document_text import extract,excerpts
from mara.company_research import CompanyLibrary


class DocumentTextTests(unittest.TestCase):
    def test_terms_are_explicit_and_long_query_falls_back_without_inventing_matches(self):
        text=('competition shapes our capital allocation. We discuss risk factors. Share repurchases are optional. '*30)
        hits,terms,mode=excerpts(text,'competition|capital allocation|risk factors|share repurchases')
        self.assertEqual(mode,'explicit_terms');self.assertEqual(len(hits),5)
        self.assertEqual({h['query'] for h in hits},set(terms))
        hits,terms,mode=excerpts(text,'competition capital allocation risk factors share repurchases')
        self.assertEqual(mode,'individual_words_fallback');self.assertTrue(hits)
        self.assertEqual(excerpts(text,'nonexistentphrase')[0],[])

    def test_pdf_has_page_scope_and_binary_is_not_treated_as_html(self):
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject,NameObject,DictionaryObject
        writer=PdfWriter();page=writer.add_blank_page(width=400,height=300)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        content=DecodedStreamObject();content.set_data(b'BT /F1 10 Tf 10 100 Td (Synthetic issuer filing competition capital allocation risk factors and cash flow disclosure. This fixture is not financial evidence.) Tj ET')
        page[NameObject('/Contents')]=writer._add_object(content);stream=io.BytesIO();writer.write(stream)
        text,meta=extract(stream.getvalue());self.assertEqual(meta['pages'],1);self.assertIn('[PDF page 1]',text);self.assertIn('Synthetic issuer',text)
        with self.assertRaises(ValueError):extract(b'%PDF-broken')
        with self.assertRaises(ValueError):extract(b'not HTML or PDF')

    def test_fallback_cannot_silently_read_a_different_annual_filing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            lib=CompanyLibrary(folder,today='2026-11-16')
            with patch.object(lib,'latest',return_value={'annual_filing':[{'url':'https://www.sec.gov/fixture','accession':'DIFFERENT'}]}),patch.object(lib,'archive') as archive:
                archive.return_value.get.side_effect=OSError('SEC unavailable')
                with self.assertRaisesRegex(ValueError,'different annual filing'):lib.filing_search('BKNG','competition','2026-11-16')
