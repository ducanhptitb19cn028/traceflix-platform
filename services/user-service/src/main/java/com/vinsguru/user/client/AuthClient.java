package com.vinsguru.user.client;

import com.vinsguru.user.dto.AccountDto;
import org.springframework.web.client.RestClient;

public class AuthClient {

    private final RestClient restClient;

    public AuthClient(RestClient restClient) {
        this.restClient = restClient;
    }

    public AccountDto getAccount(Integer userId) {
        return this.restClient.get()
                              .uri("/api/auth/{userId}", userId)
                              .retrieve()
                              .body(AccountDto.class);
    }

}
