import io,unittest
from unittest.mock import patch
from mara.document_text import extract,excerpts
from mara.company_research import CompanyLibrary


class DocumentTextTests(unittest.TestCase):
    def test_omitted_end_tags_do_not_hide_following_rows_cells_or_paragraphs(self):
        raw=b'''<html><body><table><tr hidden><td>HIDDEN_ROW</td><tr><td>VISIBLE_ROW</td><td>123</td></table>
        <table><tr><td hidden>HIDDEN_CELL<td>VISIBLE_CELL</table>
        <p hidden>HIDDEN_PARAGRAPH<p>VISIBLE_PARAGRAPH: issuer disclosure with units and period retained.
        <ul><li hidden>HIDDEN_ITEM<li>VISIBLE_ITEM</ul></body></html>'''
        text,_=extract(raw)
        for name in ('ROW','CELL','PARAGRAPH','ITEM'):
            self.assertNotIn('HIDDEN_'+name,text);self.assertIn('VISIBLE_'+name,text)
        self.assertIn('123',text)
    def test_extraction_failure_is_not_reported_as_transport_failure(self):
        import tempfile
        from mara.document_text import ExtractionError
        with tempfile.TemporaryDirectory() as folder:
            lib=CompanyLibrary(folder,today='2026-11-18')
            body={'entity':'Synthetic issuer','annual_filing':[{'form':'10-K','url':'https://www.sec.gov/fixture','accession':'0000000001-26-000001'}]}
            with patch.object(lib,'latest',return_value=body),patch.object(lib,'archive') as archive,patch('mara.company_research.extract',side_effect=ExtractionError('source_text_extraction_failed')):
                archive.return_value.get.return_value=(b'%PDF-fixture',{'sha256':'a'*64})
                with self.assertRaisesRegex(ValueError,'source_text_extraction_failed') as error:lib.filing_search('FIX','disclosure','2026-11-18')
                self.assertEqual(error.exception.attempts[0]['status'],'source_text_extraction_failed')
    def test_hidden_nested_siblings_voids_and_table_semantics(self):
        raw=b'''<html><body><div hidden>hidden parent<span>hidden child</span></div>
        <input hidden><p>Visible issuer Form 10-Q quarter ended September 30, 2026.</p>
        <div style="DISPLAY : none !important; display: block">hidden priority</div>
        <div style="display:none;display:block">Visible override</div>
        <table><tr><th>USD millions</th><th>2026</th></tr><tr><td>Operating loss</td><td>(125.0)</td></tr>
        <tr style="display:none"><td>hidden duplicate 999</td></tr></table>
        <p>Visible following disclosure preserves unit, period and negative signs -12.5.</p></body></html>'''
        text,meta=extract(raw)
        for term in ('hidden parent','hidden child','hidden priority','hidden duplicate'):self.assertNotIn(term,text)
        for term in ('Visible issuer','Visible override','USD millions','2026','(125.0)','-12.5','Visible following'):self.assertIn(term,text)
        self.assertIn(' | ',text);self.assertEqual(meta['explicit_hidden_elements_skipped'],4)
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
        import os,tempfile
        previous=os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as unrelated:
                os.chdir(unrelated);embedded,_=extract(stream.getvalue())
                self.assertEqual(embedded,text)
        finally:os.chdir(previous)
        writer.encrypt('',owner_password='synthetic-owner');public=io.BytesIO();writer.write(public)
        public_text,_=extract(public.getvalue());self.assertIn('Synthetic issuer',public_text)
        writer.encrypt('synthetic-required-password');protected=io.BytesIO();writer.write(protected)
        with self.assertRaises(ValueError):extract(protected.getvalue())
        with self.assertRaises(ValueError):extract(b'%PDF-broken')
        with self.assertRaises(ValueError):extract(b'not HTML or PDF')

    def test_fallback_cannot_silently_read_a_different_annual_filing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            lib=CompanyLibrary(folder,today='2026-11-16')
            with patch.object(lib,'latest',return_value={'annual_filing':[{'url':'https://www.sec.gov/fixture','accession':'DIFFERENT'}]}),patch.object(lib,'archive') as archive:
                archive.return_value.get.side_effect=OSError('SEC unavailable')
                with self.assertRaisesRegex(ValueError,'no_verified_same_filing_source'):lib.filing_search('BKNG','competition','2026-11-16')
