import io.anserini.analysis.DefaultEnglishAnalyzer;
import org.apache.lucene.analysis.Analyzer;
import org.apache.lucene.document.Document;
import org.apache.lucene.index.DirectoryReader;
import org.apache.lucene.index.StoredFields;
import org.apache.lucene.queryparser.classic.QueryParser;
import org.apache.lucene.search.*;
import org.apache.lucene.search.similarities.BM25Similarity;
import org.apache.lucene.store.MMapDirectory;
import java.nio.file.Paths;

// Read-only full-Lucene-syntax searcher over the same on-disk Anserini index.
// Usage: java BoolSearch <indexDir> <k> '<query>' [snippetChars=200, -1=full]
public class BoolSearch {
  public static void main(String[] a) throws Exception {
    String indexDir = a[0]; int k = Integer.parseInt(a[1]); String qstr = a[2];
    int snip = a.length > 3 ? Integer.parseInt(a[3]) : 200;
    try (DirectoryReader reader = DirectoryReader.open(MMapDirectory.open(Paths.get(indexDir)))) {
      IndexSearcher searcher = new IndexSearcher(reader);
      searcher.setSimilarity(new BM25Similarity(1.2f, 0.75f));
      Analyzer analyzer = DefaultEnglishAnalyzer.newDefaultInstance();
      QueryParser qp = new QueryParser("contents", analyzer);
      qp.setDefaultOperator(QueryParser.Operator.OR);
      Query q = qp.parse(qstr);
      System.out.println("PARSED : " + q);
      TopDocs td = searcher.search(q, k);
      System.out.println("totalHits: " + td.totalHits);
      StoredFields sf = searcher.storedFields();
      int rank = 1;
      for (ScoreDoc sd : td.scoreDocs) {
        Document d = sf.document(sd.doc);
        String id = d.get("id");
        String c = d.get("contents"); if (c == null) c = "";
        c = c.replaceAll("\\s+", " ");
        String show = (snip < 0 || c.length() <= snip) ? c : c.substring(0, snip);
        System.out.printf("[%d] %s score=%.2f%n    %s%n", rank++, id, sd.score, show);
      }
    }
  }
}
