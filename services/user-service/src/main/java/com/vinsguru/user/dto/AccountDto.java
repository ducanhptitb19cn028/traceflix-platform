package com.vinsguru.user.dto;

/** Mirror of auth-service's AccountDto (downstream response). */
public record AccountDto(Integer id,
                         String username,
                         String role) {
}
