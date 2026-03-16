#!/usr/bin/env bash
# Register Blackbox custom search attributes with the Temporal server.
#
# Run once after starting Temporal:
#   bash scripts/register_search_attributes.sh
#
# Requires: temporal CLI  (https://docs.temporal.io/cli)
#   brew install temporal   (macOS)
#   or download from GitHub releases

set -euo pipefail

NAMESPACE="${TEMPORAL_NAMESPACE:-default}"

echo "Registering Blackbox search attributes in namespace '$NAMESPACE'..."

temporal operator search-attribute create \
  --namespace "$NAMESPACE" \
  --name BlackboxModelVersion --type Keyword

temporal operator search-attribute create \
  --namespace "$NAMESPACE" \
  --name BlackboxDecision --type Keyword

temporal operator search-attribute create \
  --namespace "$NAMESPACE" \
  --name BlackboxFraudScore --type Int

temporal operator search-attribute create \
  --namespace "$NAMESPACE" \
  --name BlackboxUserCohort --type Int

temporal operator search-attribute create \
  --namespace "$NAMESPACE" \
  --name BlackboxShippingCountry --type Keyword

temporal operator search-attribute create \
  --namespace "$NAMESPACE" \
  --name BlackboxOrderAmount --type Double

echo "Done. Registered 6 custom search attributes."
