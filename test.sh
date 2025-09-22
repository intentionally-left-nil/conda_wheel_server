#! /bin/bash
set -euo pipefail

SCRIPT_DIR=$(dirname "$(realpath "$0")")

rm -rf ./repodata/repodata || true
rm -rf ./repodata/stubs || true

curl --fail --silent http://localhost:8000
echo "PASS: Homepage loads successfully"

curl -X POST --fail --silent "localhost:8000/channels/test_channel/noarch/repodata.json" -u admin:password -F "file=@$SCRIPT_DIR/sample_repodata.json"
echo "PASS: Successfully uploaded repodata"

stubs=$(curl --fail --silent http://localhost:8000/stubs | jq -c '.stubs')
if [ "$stubs" != "[]" ]; then
  echo "FAIL: .stubs is not an empty array: $stubs"
  exit 1
fi
echo "PASS: Getting initial stubs"

curl -X POST "localhost:8000/stubs" -u admin:password -F "file=@$SCRIPT_DIR/sample_stub.tar.bz2"
echo "PASS: Uploading a stub file"

stubs=$(curl --fail --silent http://localhost:8000/stubs | jq -c '.stubs')
expected_hash=$(sha256sum "$SCRIPT_DIR/sample_stub.tar.bz2" | cut -c1-8)
if [ "$stubs" != "[\"$expected_hash\"]" ]; then
  echo "FAIL: .stubs $stubs does not match [\"$expected_hash\"]"
  exit 1
fi
echo "PASS: uploading the stub file"

actual_hash=$(curl --fail --silent "localhost:8000/channels/test_channel/noarch/_c_7294187_1f18d57-0.1-false_0_$expected_hash.tar.bz2" | sha256sum | cut -c1-8)

if [ "$actual_hash" != "$expected_hash" ]; then
  echo "FAIL: Hash mismatch: $actual_hash != $expected_hash"
  exit 1
fi
echo "PASS: Downloading the stub file"

status_code=$(curl --silent --output /dev/null --write-out "%{http_code}" "localhost:8000/channels/test_channel/noarch/_c_7294187_1f18d57-0.1-false_0_wrong_hash.tar.bz2")
if [ "$status_code" -ne 404 ]; then
  echo "FAIL: Expected 404 status code, got $status_code"
  exit 1
fi
echo "PASS: Correctly returned 404 status code for non-existent file"

# Test subchannel routes
echo "Testing subchannel routes..."

# Test GET repodata with subchannel (should return 404 initially for new subchannel)
status_code=$(curl --silent --output /dev/null --write-out "%{http_code}" "localhost:8000/psm/channels/test_channel/new_subchannel/noarch/repodata.json")
if [ "$status_code" -ne 404 ]; then
  echo "FAIL: Expected 404 status code for non-existent subchannel repodata, got $status_code"
  exit 1
fi
echo "PASS: Correctly returned 404 for non-existent subchannel repodata"

# Test POST repodata with subchannel
curl -X POST --fail --silent "localhost:8000/psm/channels/test_channel/test_subchannel/noarch/repodata.json" -u admin:password -F "file=@$SCRIPT_DIR/sample_repodata.json"
echo "PASS: Successfully uploaded repodata to subchannel"

# Test GET repodata with subchannel (should now return the file)
curl --fail --silent "localhost:8000/psm/channels/test_channel/test_subchannel/noarch/repodata.json" > /dev/null
echo "PASS: Successfully retrieved repodata from subchannel"

# Test GET wheel with subchannel (should redirect)
status_code=$(curl --silent --output /dev/null --write-out "%{http_code}" "localhost:8000/psm/channels/test_channel/test_subchannel/noarch/some-package-1.0-py3-none-any.whl")
if [ "$status_code" -ne 307 ]; then
  echo "FAIL: Expected 307 redirect for wheel with subchannel, got $status_code"
  exit 1
fi
echo "PASS: Successfully redirected wheel request with subchannel"

# Test GET tarball with subchannel (should work with existing stub)
status_code=$(curl --silent --output /dev/null --write-out "%{http_code}" "localhost:8000/psm/channels/test_channel/test_subchannel/noarch/_c_7294187_1f18d57-0.1-false_0_$expected_hash.tar.bz2")
if [ "$status_code" -ne 200 ]; then
  echo "FAIL: Expected 200 for tarball with subchannel, got $status_code"
  exit 1
fi
echo "PASS: Successfully retrieved tarball with subchannel"

# Test invalid subchannel name (should return 400)
status_code=$(curl --silent --output /dev/null --write-out "%{http_code}" "localhost:8000/psm/channels/test_channel/invalid-subchannel!/noarch/repodata.json")
if [ "$status_code" -ne 400 ]; then
  echo "FAIL: Expected 400 for invalid subchannel name, got $status_code"
  exit 1
fi
echo "PASS: Correctly rejected invalid subchannel name"

# Test DELETE subchannel
curl -X DELETE --fail --silent "localhost:8000/psm/channels/test_channel/test_subchannel" -u admin:password
echo "PASS: Successfully deleted subchannel"

# Verify subchannel is deleted (should return 404)
status_code=$(curl --silent --output /dev/null --write-out "%{http_code}" "localhost:8000/psm/channels/test_channel/test_subchannel/noarch/repodata.json")
if [ "$status_code" -ne 404 ]; then
  echo "FAIL: Expected 404 after deleting subchannel, got $status_code"
  exit 1
fi
echo "PASS: Subchannel properly deleted"

echo "All tests passed"
