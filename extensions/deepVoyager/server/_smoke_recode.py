import sys
sys.path.insert(0, ".ray")
import run_pipeline as rp  # noqa: F401  (импорт исполняет reconfigure stdout->utf-8)

print("before-write encoding=%s errors=%s" % (sys.stdout.encoding, sys.stdout.errors))
# ровно та строка, что роняла прогон: кириллица + em-dash + битые байты (U+FFFD) из логов Ray
line = ("[2026-10-25T00:53:58] battles 0% \u2014 [pool CHAOS] (ray) "
        "\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd\ufffd"
        "\ufffd\ufffd\ufffd=3 shards=12 canon=False count=2 seed=133\n")
sys.stdout.write(line)
sys.stdout.flush()
print("SMOKE-OK: write_status stdout не упал")
