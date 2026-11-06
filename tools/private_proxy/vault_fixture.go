// Credential-free TLS CONNECT acceptance for AzureRM 3.117.1's data-plane SDK.
package main

import (
	"context"
	"fmt"
	"os"
	"time"

	"github.com/tombuildsstuff/kermit/sdk/keyvault/7.4/keyvault"
)

func main() {
	client := keyvault.New()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	result, err := client.GetSecret(ctx, "https://llmexample-kv-123abc.vault.azure.net", "fixture", "")
	if err != nil {
		fmt.Fprintln(os.Stderr, "Key Vault SDK fixture request failed")
		os.Exit(1)
	}
	if result.Value == nil || *result.Value != "synthetic-not-a-secret" {
		fmt.Fprintln(os.Stderr, "Key Vault SDK fixture response differs")
		os.Exit(1)
	}
	fmt.Println("Pinned provider Key Vault SDK TLS CONNECT passed")
}
