package com.vinsguru.auth.service;

import com.vinsguru.auth.dto.AccountDto;
import com.vinsguru.auth.dto.AuthResult;
import com.vinsguru.auth.repository.AccountRepository;
import org.springframework.stereotype.Service;

import java.util.Optional;

@Service
public class AuthService {

    private final AccountRepository repository;

    public AuthService(AccountRepository repository) {
        this.repository = repository;
    }

    public AuthResult validate(String token) {
        return this.repository.findByToken(token)
                              .map(a -> new AuthResult(true, a.getUsername(), a.getRole()))
                              .orElseGet(AuthResult::invalid);
    }

    public Optional<AccountDto> getAccount(Integer userId) {
        return this.repository.findById(userId)
                              .map(a -> new AccountDto(a.getId(), a.getUsername(), a.getRole()));
    }

}
